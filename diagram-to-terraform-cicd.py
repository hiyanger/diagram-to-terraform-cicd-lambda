import boto3
import json
import os
import base64
import requests

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
                            "media_type": "image/jpeg",
                            "data": encoded_string
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "画像をもとにTerraformコードを生成する。"
                            "variableにstringでaws_access_key_idとaws_secret_access_keyを定義し、providerブロックに記述する"
                            "providerを記述し、東京リージョンとする。"
                            "terraform ブロックは不要"
                            "terraformのコードのみを出力し、出力ファイルの前後に不要なテキストは含めない。"
                            "```の囲い込みは含めない。"
                            "記述しなくても設定が変わらないパラメータは記述しない。"
                            "Terraform名にAWSサービス名は含めない。"
                            "Terraform名の出力に迷ったら diagram と出力する。"
                            "各リソースの接続に必要なリソースブロックは適宜補完する。"
                            "タグ名はすべてdiagram-サービス名とする。"
                            "EC2のAMIは ami-03f584e50b2d32776 に固定し、コメントは「AL2023」と出力する。"
                            "EC2はSSHキー hiyama-diagram を設定する。"
                            "EC2にはパブリックIPを付与する"
                            "EC2はセキュリティグループを設定し、SSH通信のみを許可する。"
                            "ingressの cidr_blocks = ['0.0.0.0/0'] には コメント 「# 適宜変更」を追加する。"
                            "セキュリティグループのegressの設定は不要。"
                        )
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
    response_body = response['body'].read().decode('utf-8')
    response_json = json.loads(response_body)
    
    # 'text'フィールドが存在すればその内容を取得
    terraform_code = None
    for content in response_json.get('content', []):
        if content['type'] == 'text':
            terraform_code = content['text']
            break

    if terraform_code is None:
        terraform_code = json.dumps(response_json, ensure_ascii=False, indent=4)
    
    # GitHubにファイルをプッシュ
    repo_name = os.environ['GITHUB_REPO']
    github_token = os.environ['GITHUB_TOKEN']
    branch_name = 'develop'
    commit_message = 'Add generated Terraform code from Bedrock'
    
    # GitHub APIのエンドポイント (ファイル名を main.tf に変更)
    api_url = f'https://api.github.com/repos/{repo_name}/contents/main.tf'
    
    # ヘッダーに認証情報を追加
    headers = {
        'Authorization': f'token {github_token}',
        'Content-Type': 'application/json'
    }

    # ファイルが存在するか確認し、SHAを取得する
    response = requests.get(api_url, headers=headers, params={'ref': branch_name})
    
    if response.status_code == 200:
        # ファイルが存在する場合はSHAを取得
        file_info = response.json()
        sha = file_info['sha']
        
        # 更新用のデータ
        create_or_update_data = {
            "message": commit_message,
            "content": base64.b64encode(terraform_code.encode('utf-8')).decode('utf-8'),
            "sha": sha,  # 更新するためにSHAが必要
            "branch": branch_name
        }
    else:
        # ファイルが存在しない場合は新規作成のデータ
        create_or_update_data = {
            "message": commit_message,
            "content": base64.b64encode(terraform_code.encode('utf-8')).decode('utf-8'),
            "branch": branch_name
        }
    
    # ファイルをアップロード (存在すれば上書き、なければ作成)
    response = requests.put(api_url, headers=headers, data=json.dumps(create_or_update_data))
    
    if response.status_code not in [200, 201]:
        return {
            'statusCode': response.status_code,
            'body': json.dumps('Failed to push file to GitHub')
        }

    # プルリクエストを作成する
    pr_url = f"https://api.github.com/repos/{repo_name}/pulls"
    pr_data = {
        "title": "Merge develop into main",
        "head": branch_name,
        "base": "main",
        "body": "This PR merges the generated Terraform code into the main branch."
    }

    pr_response = requests.post(pr_url, headers=headers, data=json.dumps(pr_data))
    
    if pr_response.status_code in [200, 201]:
        return {
            'statusCode': 200,
            'body': json.dumps('File successfully pushed and pull request created')
        }
    else:
        return {
            'statusCode': pr_response.status_code,
            'body': json.dumps('Failed to create pull request')
        }
