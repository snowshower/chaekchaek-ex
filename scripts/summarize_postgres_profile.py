"""Read only numeric profiling properties, never failure text or DB credentials."""
import sys
import xml.etree.ElementTree as ET


def summarize(path):
    for case in ET.parse(path).iter("testcase"):
        values = {}
        for prop in case.findall("properties/property"):
            if prop.get("name", "").startswith(("profile.", "postgres.")):
                values[prop.get("name")] = float(prop.get("value"))
        # Print the test name, not captured logs, request data or exception text.
        print(case.get("name"))
        get = lambda key: values.get("profile." + key, 0.0)
        body = get("body.test.body.seconds")
        http = get("body.http.actions.seconds") + get("body.http.bootstrap.seconds")
        direct = sum(value for key, value in values.items()
                     if key.startswith("profile.body.direct_db.") and key.endswith(".seconds"))
        http_db = sum(value for key, value in values.items()
                      if key.startswith("profile.body.http_db.") and key.endswith(".seconds"))
        print(f"body={body:.3f}s; HTTP={http:.3f}s; direct DB/report={direct:.3f}s; outside HTTP/DB={body-http-direct:.3f}s")
        print(f"HTTP DB={http_db:.3f}s; HTTP non-DB/framework={http-http_db:.3f}s")
        for key in ("client.participant", "client.bootstrap", "client.api.book_view", "client.api.emoji", "client.api.short",
                    "db.acquire", "db.close", "setup.init_db.1", "setup.init_db.2"):
            print(f"{key}: calls={get(key+'.calls'):.0f}, seconds={get(key+'.seconds'):.3f}")
        sql_count = sum(value for key, value in values.items() if key.startswith("profile.sql.") and key.endswith(".calls"))
        print(f"application SQL statements={sql_count:.0f}")
        for stage in ("SQL sent", "advisory lock", "write lock held", "connect", "close"):
            print(f"{stage}: calls={values.get('postgres.'+stage+'.calls',0):.0f}, seconds={values.get('postgres.'+stage+'.seconds',0):.3f}")


if __name__ == "__main__":
    summarize(sys.argv[1])
