import sqlite3

c = sqlite3.connect("data/eval_results.sqlite")
rows = c.execute(
    "SELECT question, predicted_sql, error, repairs "
    "FROM eval_results WHERE executable=0 "
    "ORDER BY created_at DESC LIMIT 5"
).fetchall()

for q, sql, err, repairs in rows:
    print("-" * 60)
    print("Q:", q)
    print("SQL:", sql)
    print("error:", err)
    print("repairs attempted:", repairs)