"""Current guide structure and byte-preserved historical resource regressions."""
import hashlib
import re

from src.infra.common import ROOT


def test_current_documentation_is_consolidated_and_has_one_versioned_result():
    pages = {str(path.relative_to(ROOT / "docs")) for path in (ROOT / "docs").rglob("*.md")}
    assert pages == {"README.md", "architecture.md", "agent-flow.md", "model.md",
                     "validation.md", "infra.md", "demo.md", "results/demo-ui1.md"}
    assert not list((ROOT / "docs").rglob("*.json"))
    index = (ROOT / "docs/README.md").read_text()
    assert all(path in index for path in pages if path != "README.md")


def test_archived_protocols_and_acceptance_records_are_byte_preserved():
    archive = ROOT / "validation/archive/docs-2026-11-02"
    checksums = dict(line.split(None, 1)[::-1] for line in (archive / "SHA256SUMS").read_text().splitlines())
    assert len(checksums) == 27
    files = {str(path.relative_to(archive)) for path in archive.rglob("*") if path.is_file() and path.name != "SHA256SUMS"}
    assert files == set(checksums)
    for relative, expected in checksums.items():
        assert hashlib.sha256((archive / relative).read_bytes()).hexdigest() == expected, relative


def test_readme_explains_agentdojo_native_authority_and_run_boundaries():
    text = (ROOT / "README.md").read_text()
    for required in ("https://arxiv.org/pdf/2406.13352", "https://github.com/ethz-spylab/agentdojo",
                     "https://github.com/agent-substrate/substrate", "https://github.com/agentgateway/agentgateway",
                     "```mermaid", "docs/architecture.md", "docs/agent-flow.md", "docs/model.md",
                     "docs/validation.md", "docs/infra.md", "docs/demo.md", "docs/results/demo-ui1.md",
                     "not a turnkey live demo", "no installed", "classifier decision computation"):
        assert required in text, required


def test_versioned_demo_report_retains_performance_denominators_and_source_ids():
    text = (ROOT / "docs/results/demo-ui1.md").read_text()
    for row in ("| D01 | 66.057 / 3 | 76.076 / 3 | 367.994 / 3 |",
                "| D02 | 58.580 / 3 | 64.699 / 3 | 590.561 / 3 |",
                "| D03 | 52.666 / 2 | 60.059 / 2 | 258.626 / 2 |",
                "| D04 | N/A | N/A | N/A |", "| D05 | N/A | N/A | N/A |"):
        assert row in text
    for required in ("18 native cases", "Startup/priming", "Actual Chromium",
                     "2392cad2ce6a4ac68939b2dcea7c8efa", "49e96b38698df8fa6b5d500d83d161809e95a9f4",
                     "358 local /223 external", "conservative holds", "#17", "1025.966ms"):
        assert required in text
    assert "Below15ms" not in text and "native_core_below15" not in text


def test_sequence_diagram_message_text_has_no_unescaped_statement_separators():
    # Mermaid treats bare semicolons as newlines, even inside message text.
    # Entity escapes such as #59; are allowed. Keep this regression offline.
    for path in (ROOT / "docs").rglob("*.md"):
        for diagram in re.findall(r"```mermaid\n(.*?)```", path.read_text(), re.DOTALL):
            if not diagram.lstrip().startswith("sequenceDiagram"):
                continue
            for line in diagram.splitlines():
                if ":" not in line:
                    continue
                message = line.split(":", 1)[1]
                unescaped = re.sub(r"#[a-zA-Z0-9]+;", "", message)
                assert ";" not in unescaped, f"{path}: unescaped semicolon in {line.strip()}"


def test_model_equations_avoid_unsupported_operatorname_macro():
    text = (ROOT / "docs/model.md").read_text()
    assert r"\operatorname" not in text
    assert r"\frac{1}{1+e^{-(z_1-z_0)/T}}" in text
    assert text.count(r"\frac{1}{|B_b|}\sum_{i\in B_b}") == 2


def test_readme_routes_model_and_mcp_traffic_through_one_gateway():
    text = (ROOT / "README.md").read_text()
    diagram = text.split("## System architecture", 1)[1].split("```mermaid\n", 1)[1].split("```", 1)[0]
    assert diagram.count("G[agentgateway:") == 1
    assert "A -->|Responses model requests and MCP tool calls| G" in diagram
    assert "G -->|model requests| L" in diagram
    assert "G -->|MCP tool calls| B" in diagram
    assert "Q -->|review model request| G" in diagram
    assert "B -->|MCP result| G" in diagram
    assert "not inside a Substrate Actor" in text
