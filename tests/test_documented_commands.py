from scripts.validate_documented_commands import validate


def test_documented_commands_exist_and_are_current() -> None:
    assert validate() == []
