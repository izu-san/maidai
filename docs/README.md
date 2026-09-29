# MaidAI ドキュメント

用途から資料を探せるように、ドキュメントを次の区分に整理しています。現行の構成・使い方を知りたい場合は、まず「導入」を参照してください。

## 導入

- [リポジトリ概要と梨乃の使い方](getting-started/リポジトリ概要と梨乃の使い方.md): 構成、技術スタック、現在できること、通知範囲
- [起動ハブの使い方](getting-started/起動ハブの使い方.md): `Start-MaidAI.ps1` の起動プロファイル
- [Qwen3.8-27B 専属メイドAI 構築手順書](getting-started/Qwen3.8-27B_専属メイドAI_構築手順書.md): Qwen ベース環境の構築・学習に関する参考手順

## 機能

- [エージェント機能一覧](features/エージェント機能一覧.md): 現在有効な機能と、既定で無効な統合

## 運用

- [Rino Agent Service API](operations/Rino_Agent_Service_API.md): Agent API、セッション、承認、イベント待機
- [Rino MCP Operations](operations/Rino_MCP_Operations.md): MCP の有効化と安全な運用
- [Rino Agent Phase 0 Runbook](operations/Rino_Agent_Phase0_Runbook.md): LLM のツール呼び出し経路を確認する検証手順

## 設計

- [Rino Agent Platform](architecture/Rino_Agent_Platform_Spec_MAF_MCP.md): MAF、MCP、ポリシー、承認の設計
- [Rino Event Bus](architecture/Rino_EventBus.md): ローカルイベントバスの設計と運用
- [Rino SwitchBot Integration](architecture/Rino_SwitchBot_Integration_Spec.md): SwitchBot 連携の仕様
- [Rino Image Generation](architecture/Rino_Image_Generation_Skeleton.md): 非同期画像生成連携の設計
- [梨乃 生活連携基盤 仕様書](architecture/梨乃_生活連携基盤_仕様書.md) / [詳細設計](architecture/梨乃_生活連携基盤_詳細設計.md): 生活イベント、通知、永続化の設計

## キャラクター設定

キャラクター設定・プロンプト関連の資料（`docs/character/`）は非公開のため、このリポジトリには含まれない。

利用者に見える基盤・機能・設定の変更時は、該当資料と「リポジトリ概要と梨乃の使い方」の改訂履歴を同じ変更で更新します。詳細はリポジトリ直下の `AGENTS.md` を参照してください。
