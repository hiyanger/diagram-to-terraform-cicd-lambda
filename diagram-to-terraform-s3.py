import boto3
import json
import os
import base64
import re

def lambda_handler(event, context):
    # S3イベントからバケット名とオブジェクトキーを取得
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    
    # S3クライアントの初期化
    s3 = boto3.client('s3')
    
    # 画像をダウンロード
    local_file_path = '/tmp/image.png'
    s3.download_file(bucket, key, local_file_path)
    
    # 画像をbase64エンコード
    with open(local_file_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    
    # Bedrockクライアントの初期化
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    
    # Bedrockに渡すリクエストボディの作成
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",  # 画像形式に合わせて変更可能
                            "data": encoded_string
                        }
                    },
                    {
                        "type": "text",
                        "text": 
                            "画像をもとにTerraformコードを生成する"
                            "東京リージョンのprovider情報のみを含める"
                            "terraformのコードのみを出力し、出力ファイルの前後に不要なテキストは含めない"
                            "```の囲い込みは含めない"
                            "各リソースの接続に必要なリソースブロックは適宜補完する"
                    }
                ]
            }
        ]
    }

    # Bedrockモデルの呼び出し
    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-5-sonnet-20240620-v1:0',
        contentType='application/json',
        accept='application/json',
        body=json.dumps(body)
    )
    
    # レスポンスの解析: StreamingBodyを文字列に変換
    response_body = response['body'].read().decode('utf-8')  # StreamingBodyを文字列に変換
    response_json = json.loads(response_body)
    
    # 'text'フィールドが存在すればその内容を取得
    terraform_code = None
    for content in response_json.get('content', []):
        if content['type'] == 'text':
            terraform_code = content['text']
            break

    # Terraformコードをそのまま保存
    if terraform_code is None:
        terraform_code = json.dumps(response_json, ensure_ascii=False, indent=4)  # デバッグ用にレスポンス全体を保存
    
    
    # S3に結果をアップロード
    destination_bucket = os.environ['DESTINATION_BUCKET']
    output_key = f"{os.path.splitext(key)[0]}_terraform_code.tf"  # 拡張子を .tf に変更
    s3.put_object(Bucket=destination_bucket, Key=output_key, Body=terraform_code)
    
    return {
        'statusCode': 200,
        'body': json.dumps(f'Terraform code saved to S3: {output_key}')
    }
