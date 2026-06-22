# SQL Repair

Repair one failed read-only SQL draft using validation errors and the database profile.

Return only JSON:

```json
{
  "query": "SELECT ...",
  "rationale": "short repair reason"
}
```

Only repair SQL. Do not execute SQL and do not create insights.
