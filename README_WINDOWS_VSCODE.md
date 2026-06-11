# Windows + VS Code セットアップ手順

この手順書では、Windows の Visual Studio Code から NSFW Detector & Annotator を起動する方法を説明します。

## 1. 事前準備

以下をインストールしてください。

- Python 3.10 以上
- Git
- Visual Studio Code
- VS Code 拡張機能:
  - Python (Microsoft)
  - Pylance (Microsoft)

## 2. ミドルウェア (ffmpeg) のインストール

このアプリは動画プレビューの変換に ffmpeg を使用します。先に ffmpeg をインストールしてください。

### 方法A: winget (推奨)

```powershell
winget install --id Gyan.FFmpeg -e
```

### 方法B: Chocolatey

```powershell
choco install ffmpeg -y
```

### 方法C: Scoop

```powershell
scoop install ffmpeg
```

### ffmpeg の確認

インストール後に新しいターミナルを開き、次を実行します。

```powershell
ffmpeg -version
```

コマンドが見つからない場合は、VS Code を再起動して PATH 設定を確認してください。

## 3. VS Code でプロジェクトを開く

1. VS Code を起動します。
2. フォルダ nsfw_detector_annotator を開きます。
3. VS Code の新しいターミナルを開きます (Terminal -> New Terminal)。

## 4. 仮想環境の作成と有効化

VS Code ターミナルで実行します。

```powershell
python -m venv .venv
```

有効化します。

- PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

- Command Prompt

```cmd
.venv\Scripts\activate.bat
```

## 5. Python 依存関係のインストール

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 6. VS Code で Python インタープリタを選択

1. Ctrl+Shift+P を押します。
2. Python: Select Interpreter を実行します。
3. このワークスペースの .venv インタープリタを選択します。

## 7. 必要なモデルファイルの確認

以下のファイルが存在することを確認してください。

- models/classification_model.pt
- models/segmentation_model.pt

## 8. アプリを起動

```powershell
streamlit run app/app.py
```

もし streamlit が見つからない場合は、次を実行します。

```powershell
python -m streamlit run app/app.py
```

ブラウザで以下を開きます。

- http://localhost:8501

## 9. トラブルシュート

### PowerShell で有効化スクリプトが実行できない

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### ffmpeg コマンドが見つからない

- ffmpeg インストール後に VS Code を再起動する
- 次のコマンドで確認する

```powershell
where ffmpeg
```

- 必要に応じて ffmpeg の bin ディレクトリを Windows PATH に追加する

### モデル読み込みエラーが出る

- models フォルダにモデルファイルがあることを確認する
- Streamlit 実行時のカレントディレクトリがプロジェクトルートであることを確認する

## 10. 任意: VS Code タスクで起動

.vscode/tasks.json に以下を定義すると、タスクから起動できます。

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Run Streamlit",
      "type": "shell",
      "command": "python -m streamlit run app/app.py",
      "group": "build",
      "problemMatcher": []
    }
  ]
}
```

Terminal -> Run Task -> Run Streamlit で実行できます。

## 11. Docker で起動する場合

Docker での起動手順は専用ドキュメントに分離しています。

- docker/README_DOCKER.md を参照してください。
- Docker 手順は `cd docker` で移動してから実行する流れです。
