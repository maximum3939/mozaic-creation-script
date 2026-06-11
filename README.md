# Docker 起動手順

この手順書では、Docker コンテナを起動し、ブラウザでアプリを開くところまでを順番に説明します。

## アプリ画面

以下はアプリの画面イメージです。

![Mozaic App Screen](pic/mozaic-screen.jpg)

## 1. 事前準備

1. Docker Desktop をインストールします。
	- ダウンロード: https://www.docker.com/products/docker-desktop/
2. Docker Desktop を起動します。
3. VS Code でプロジェクトフォルダを開きます。
4. VS Code で新しいターミナルを開きます (Terminal -> New Terminal)。

確認コマンド:

```powershell
docker --version
docker compose version
```

どちらもバージョンが表示されれば準備完了です。

## 2. Docker ファイルの配置

このプロジェクトでは Docker 関連ファイルを次に配置しています。

- docker/Dockerfile
- docker/docker-compose.yml
- .dockerignore

補足:

- .dockerignore は Docker の仕様上、ビルドコンテキストのルートに必要です。
- この構成ではビルドコンテキストがプロジェクトルートのため、.dockerignore はルート配置です。

## 3. コンテナをビルドして起動

VS Code ターミナルで、まず Docker ディレクトリへ移動します。

```powershell
cd docker
```

その後、次を実行します。

```powershell
docker compose up --build -d
```

初回はイメージビルドがあるため数分かかることがあります。

## 4. 起動状態を確認

コンテナ状態を確認します。

```powershell
docker compose ps
```

app サービスが Up になっていれば起動成功です。

必要に応じてログを確認します。

```powershell
docker compose logs -f
```

ログの追尾を終了する場合は Ctrl + C を押します。

## 5. ブラウザで開く

1. ブラウザを開きます。
2. 次の URL にアクセスします。

- http://localhost:8501

表示されれば起動完了です。

PowerShell から直接開く場合:

```powershell
start http://localhost:8501
```

## 6. 停止と再起動

停止:

```powershell
docker compose down
```

再起動 (ビルドなし):

```powershell
docker compose up -d
```

依存関係変更後の再起動 (再ビルドあり):

```powershell
docker compose up --build -d
```

## 7. データ永続化

- uploaded_media はホストとコンテナで共有されるため、コンテナ再作成後も保持されます。

## 8. トラブルシュート

### 8-1. 起動しない

```powershell
docker compose logs -f
```

ログにエラー内容が出るので、内容に応じて対処します。

### 8-2. ブラウザで開けない

1. docker compose ps で app が Up か確認
2. URL が http://localhost:8501 になっているか確認
3. セキュリティソフトやローカルファイアウォールを確認

### 8-3. モデル読み込みエラー

次のファイルが存在することを確認します。

- models/classification_model.pt
- models/segmentation_model.pt

### 8-4. ffmpeg 関連エラー

キャッシュなしで再ビルドします。

```powershell
docker compose build --no-cache
docker compose up -d
```
