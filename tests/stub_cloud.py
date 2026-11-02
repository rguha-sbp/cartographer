from cartographer.clouds.base import Cloud


class StubCloud(Cloud):
    def icon_style(self, name: str) -> str:
        return f"shape=stub.{name};"
