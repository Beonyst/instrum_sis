import psycopg2

connection = psycopg2.connect(
    dbname="searchengine",
    user="postgres",
    password="123456",
    host="127.0.0.1",
    port=5432
)

print("Подключение успешно")

connection.close()