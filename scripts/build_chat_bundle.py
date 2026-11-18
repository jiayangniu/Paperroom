"""Build only the Claude Desktop extension (compatible with the 0.2 invocation)."""
from build_packages import ROOT, build


if __name__ == "__main__":
    build(ROOT / "packages", desktop_only=True)
