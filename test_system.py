from connections import redis_client, get_db_connection, query_ollama

# Test Redis
redis_client.set("test_key", "hello")
print("Redis:", redis_client.get("test_key"))

# Test PostgreSQL
conn = get_db_connection()
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS test (id SERIAL PRIMARY KEY, name TEXT)")
cur.execute("INSERT INTO test (name) VALUES (%s)", ("working",))
conn.commit()

cur.execute("SELECT * FROM test")
print("Postgres:", cur.fetchall())

cur.close()
conn.close()

# Test Ollama
response = query_ollama("Say hello in one sentence")
print("Ollama:", response)
