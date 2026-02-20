poetry run ingest-rulebook `
  --pdf ".\rulebooks\wingspan\wingspan_rulebook.pdf" `
  --game-id wingspan `
  --game-name "Wingspan" `
  --source-name rulebook `
  --source-type rulebook `
  --version "1st-ed" `
  --db ".\rules_store\rules.db" `
  --index ".\rules_store\index.faiss"


poetry run search-rules `
  --db ".\rules_store\rules.db" `
  --index ".\rules_store\index.faiss" `
  --game-id wingspan `
  --query "do tucked cards count for end of round goals?" `
  --k-final 5 `
  --show-text

