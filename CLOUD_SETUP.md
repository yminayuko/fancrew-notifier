# クラウド監視 → iPhone通知

この版はGitHub Actionsで動かします。PCの常時稼働は不要です。GitHubアカウントと、iPhoneのntfyアプリへの登録が必要です。ファイルを保存するだけでは監視は始まりません。

## 動作

- 毎時17分に起動予定（日本時間でも毎時17分）。GitHub側の混雑により遅延・実行抜けが生じることがあり、時刻の保証はありません。
- 検索結果全ページを取得し、詳細は最大120件ずつ順番に確認します。約460件なら全体を回るのに約4時間が目安です。件数・取得失敗・実行遅延により増えます。
- 最初の全体巡回は基準収集です。その後の新規案件・実際に終了を観測した後の応募ボタン復活をiPhoneへ通知します。
- 状態と続きの位置をGitHubのArtifactとして保存し、次回に復元します。通知済み案件を繰り返し通知しません。
- 通知トピックはGitHub ActionsのSecretから読み取ります。公開コード・実行ログ・Artifactにトピック名を保存しません。
- 人間確認や403/429を検出したら停止フラグを保存します。次回以降もサイトへ接続せず、手動再開まで停止状態を維持します。
- 1回の上限時間は50分です。取得エラーや時間切れで巡回を完了できない場合は、次回に同じ区間を再試行します。

## 初期設定

1. iPhoneにntfyをインストールし、通知を許可します。
2. 通知トピックを用意します。前の版で `--setup-iphone` を実行済みなら、その `fancrew-` と32桁の小文字16進数のトピック名をそのまま使えます。パスワードのように扱い、GitHubのコードやチャットには貼らないでください。
3. GitHubに専用リポジトリを作成します。前の版からの更新でも、同じファイル構成を使います。
4. ZIP内の `fancrew_notifier` フォルダの**中身**をリポジトリの最上位に配置します。`fancrew_notifier/` という外側のフォルダごとは配置しないでください。
5. 特に `.github/workflows/monitor.yml` が必要です。ドットで始まるフォルダが見えない場合は、GitHub画面の「Add file → Create new file」でこの正確なファイル名を入力し、同梱YAMLの内容を貼り付けて保存できます。GitHubの既定ブランチ（通常main）に保存してください。
6. リポジトリの **Settings → Secrets and variables → Actions → New repository secret** を開き、名前 `NTFY_TOPIC`、値に通知トピック名を登録します。
7. iPhoneのntfyアプリで、サーバー `https://ntfy.sh` と同じトピック名を購読します。
8. **Actions → Fancrew cloud monitor → Run workflow** で `test-notification` を選び実行します。
9. iPhoneへ「ファンくる通知テスト」が届くことを確認します。続いて `monitor` を選んで手動実行すると基準収集が始まります。以降は時刻表に従って実行します。

クラウド設定のためのGitHub接続を行えば、リポジトリへの配置をこちらで進められる場合があります。Secretの設定やiPhoneでの到着確認はご自身の画面で行ってください。パスワード・トピック名を会話に送る必要はありません。

## PCを一度も使わずトピックを作る場合

iPhoneで開ける `TOPIC_SETUP.html` を同梱しています。SafariでJavaScriptを実行できる形で開くと128ビットの乱数でトピック名を生成できます。生成は端末内で行い、外部へ送信しません。iPhoneの「ファイル」のプレビューではJavaScriptが動作しないことがあるため、この画面はGitHubへの配置後、Webページとして利用するか、PCのブラウザで開いてください。GitHubへの接続後に、iPhoneで使える設定画面の公開を進められます。生成された名前をSecretとntfyの両方へコピーします。

## 料金とリポジトリの公開範囲

- 公開リポジトリの標準GitHub-hosted runnerは無料利用の対象です。コード・取得結果・実行ログは公開情報として扱ってください。通知トピックだけは必ずSecretへ入れます。
- 非公開リポジトリのGitHub Freeには月2,000分の実行枠があります。毎時監視では無料枠を超える可能性が高いため、完全無料とは限りません。クレジットカード登録済みの場合は、実行前にActionsの利用予算・課金上限設定を確認してください。料金設定をこのプログラムが変更することはありません。
- 初期の実行時間を見て、必要なら `.github/workflows/monitor.yml` のcronを `17 */4 * * *`（4時間ごと）に変更できます。その場合、約460件の全体巡回は約16時間になります。
- 公開リポジトリは60日間のリポジトリ活動がないと定期実行が無効化されます。Actionsが無効になっていないか定期的に確認してください。

## 確認・停止・再開

- 実行結果：Actionsタブで各実行の成功／失敗とログを確認します。
- 詳細：各実行のArtifactsの `fancrew-diagnostics` に `monitor.log` と `available.html` が保存されます。
- 停止：Actionsで **Disable workflow**。停止フラグで停止中の場合は、原因を確認するまで再開しないでください。
- 再開：原因解消後、手動の **Run workflow → resume**。停止フラグを解除して1区間確認します。
- 状態Artifactの保存期間は30日です。30日以上停止する、Artifactを削除する、リポジトリを作り直すと、基準収集がやり直しになる場合があります。
- 巡回失敗と通知送信失敗はログに記録します。通知サービス自体に接続できないとエラーのプッシュ通知も届きません。Actionsの失敗通知も有効にすると確認しやすくなります。

## 制約・検証

東京都・1人で来店できるグルメ案件が対象です。公開ページの応募ボタンを確認する方式で、個人の年齢・性別・過去の応募履歴による資格や実際の当選は保証しません。短時間だけ空いた枠は検出できない場合があります。

募集判定・iPhone通知データ・クラウドの順次確認・履歴復元を模擬テストで検証しています。GitHub Actionsでの実行、ファンくるのクラウド接続可否、iPhoneへの到着は公開後に確認する必要があります。

公式資料：
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/rest/actions/artifacts
- https://docs.ntfy.sh/subscribe/phone/
