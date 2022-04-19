import random
import sqlite3
import string
import time

create_statement = """
CREATE TABLE IF NOT EXISTS database_threading_test
(
    symbol TEXT,
    ts INTEGER,
    o REAL,
    h REAL,
    l REAL,
    c REAL,
    vf REAL,
    vt REAL,
    PRIMARY KEY(symbol, ts)
)
"""
insert_statement = "INSERT INTO database_threading_test VALUES(?,?,?,?,?,?,?,?)"
select_statement = "SELECT * from database_threading_test"


def generate_values(count=100):
    end = int(time.time()) - int(time.time()) % 900
    symbol = "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(10)
    )
    ts = list(range(end - count * 900, end, 900))
    for i in range(count):
        yield (
            symbol,
            ts[i],
            random.random() * 1000,
            random.random() * 1000,
            random.random() * 1000,
            random.random() * 1000,
            random.random() * 1e9,
            random.random() * 1e5,
        )


def generate_values_list(symbols=1000, count=100):
    values = []
    for _ in range(symbols):
        values.extend(generate_values(count))
    return values


def main():
    lst = generate_values_list()
    conn = sqlite3.connect(":memory:")
    with conn:
        conn.execute(create_statement)
        conn.executemany(insert_statement, lst)
    results = conn.execute(select_statement).fetchall()
    print(f"There are {len(results)} items in teh db")


if __name__ == "__main__":
    main()
