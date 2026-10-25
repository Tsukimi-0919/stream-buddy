# セキュリティポリシー / Security Policy

## 脆弱性の報告

脆弱性を見つけた場合は、**公開の Issue には書かず**、GitHub の
[Private vulnerability reporting](../../security/advisories/new) から報告してください。

To report a vulnerability, please use GitHub's **Private vulnerability reporting**
(Security tab → "Report a vulnerability"). Do not open a public issue.

## 対応について

- 個人で開発しているため、返信や修正の期限はお約束できません
- 報告いただいた内容は確認し、必要に応じて修正と GitHub Security Advisory の公開を行います

## 対象バージョン

最新のリリースのみを対象とします。

## このツールの安全設計

- 通信は PC 内（`127.0.0.1`）に限定し、外部へは送信しません
- 音声は保存せず、メモリ上で処理して破棄します
- ホットキーは登録したキーのみを受け取り、他のキー入力は記録しません

詳細は [docs/threat-model.md](docs/threat-model.md) を参照してください。
