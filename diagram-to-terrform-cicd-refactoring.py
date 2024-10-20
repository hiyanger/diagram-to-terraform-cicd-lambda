import boto3
import json
import os
import base64
import requests

def lambda_handler(event, context):
    # S3イベントからバケット名とオブジェクトキーを取得
    s3 = boto3.client('s3')
    bucket, key = event['Records'][0]['s3']['bucket']['name'], event['Records'][0]['s3']['object']['key']
    local_file_path = '/tmp/image.png'
    
    # S3から画像をダウンロード
    s3.download_file(bucket, key, local_file_path)

    # 画像をbase64エンコード
    with open(local_file_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

    # Bedrockに渡すリクエストボディの作成
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded_string}},
                {"type": "text", "text": (
                    "画像をもとにTerraformコードを生成する。"
                    "variableにstringでaws_access_key_idとaws_secret_access_keyを定義し、providerブロックに記述する。"
                    "providerを記述し、東京リージョンとする。"
                    "terraform ブロックは不要。"
                    "terraformのコードのみを出力し、出力ファイルの前後に不要なテキストは含めない。"
                    "```の囲い込みは含めない。"
                    "記述しなくても設定が変わらないパラメータは記述しない。"
                    "Terraform名にAWSサービス名は含めない。"
                    "Terraform名の出力に迷ったら diagram と出力する。"
                    "各リソースの接続に必要なリソースブロックは適宜補完する。"
                    "タグ名はすべてdiagram-サービス名とする。"
                    "EC2のAMIは ami-03f584e50b2d32776 に固定し、コメントは「AL2023」と出力する。"
                    "EC2はSSHキー hiyama-diagram を設定する。"
                    "EC2にはパブリックIPを付与する。"
                    "EC2はセキュリティグループを設定し、SSH通信のみを許可する。"
                    "ingressの cidr_blocks = ['0.0.0.0/0'] には コメント 「# 適宜変更」を追加する。"
                    "セキュリティグループのegressの設定は不要。"
                )}
            ]
        }]
    }

    # Bedrockモデルの呼び出し
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    response_body = bedrock.invoke_model(
        modelId='anthropic.claude-3-5-sonnet-20240620-v1:0',
        contentType='application/json',
        accept='application/json',
        body=json.dumps(body)
    )['body'].read().decode('utf-8')

    # レスポンスからTerraformコードを取得
    terraform_code = next((c['text'] for c in json.loads(response_body).get('content', []) if c['type'] == 'text'), None) or json.dumps(response_body)

    # GitHubのリポジトリ名とトークン、ブランチ名を環境変数から取得
    repo_name, github_token, branch_name = os.environ['GITHUB_REPO'], os.environ['GITHUB_TOKEN'], 'develop'
    api_url = f'https://api.github.com/repos/{repo_name}/contents/main.tf'
    headers = {'Authorization': f'token {github_token}', 'Content-Type': 'application/json'}
    
    # ファイルのSHAを取得して、ファイルが存在する場合は上書き、新規作成の場合は新規作成
    sha = requests.get(api_url, headers=headers, params={'ref': branch_name}).json().get('sha')
    create_or_update_data = {
        "message": "Add generated Terraform code from Bedrock",
        "content": base64.b64encode(terraform_code.encode('utf-8')).decode('utf-8'),
        "sha": sha, "branch": branch_name
    } if sha else {
        "message": "Add generated Terraform code from Bedrock",
        "content": base64.b64encode(terraform_code.encode('utf-8')).decode('utf-8'),
        "branch": branch_name
    }

    # ファイルをGitHubにアップロード
    requests.put(api_url, headers=headers, data=json.dumps(create_or_update_data))

    # プルリクエストを作成
    pr_data = {"title": "Merge develop into main", "head": branch_name, "base": "main", "body": "This PR merges the generated Terraform code into the main branch."}
    pr_url = f"https://api.github.com/repos/{repo_name}/pulls"

    # 成功メッセージの返却
    return {
        'statusCode': 200,
        'body': json.dumps('File successfully pushed and pull request created') if requests.post(pr_url, headers=headers, data=json.dumps(pr_data)).status_code in [200, 201] else 'Failed to create pull request'
    }
