from scripts.summarize_postgres_profile import summarize


def test_summary_partitions_wall_time_without_printing_failure_text(tmp_path, capsys):
    path = tmp_path / "profile.xml"
    path.write_text('''<testsuites><testsuite><testcase name="targeted">
    <properties>
      <property name="profile.body.test.body.seconds" value="100"/>
      <property name="profile.body.http.actions.seconds" value="70"/>
      <property name="profile.body.direct_db.sql.SELECT.seconds" value="20"/>
      <property name="profile.body.http_db.db.acquire.seconds" value="10"/>
      <property name="profile.body.http_db.sql.batch.seconds" value="50"/>
    </properties>
    <failure>postgresql://private-user:private-password@private-host/database</failure>
    </testcase></testsuite></testsuites>''', encoding="utf-8")
    summarize(path)
    output = capsys.readouterr().out
    assert "outside HTTP/DB=10.000s" in output
    assert "HTTP non-DB/framework=10.000s" in output
    assert "private" not in output
