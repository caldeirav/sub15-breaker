"""Current guide structure and byte-preserved historical resource regressions."""
import hashlib

from src.infra.common import ROOT


def test_current_documentation_is_consolidated_and_has_one_versioned_result():
    pages = {str(path.relative_to(ROOT / "docs")) for path in (ROOT / "docs").rglob("*.md")}
    assert pages == {"README.md", "architecture.md", "agent-flow.md", "model.md",
                     "validation.md", "infra.md", "demo.md", "results/demo-nd11-nd12.md"}
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
                     "docs/validation.md", "docs/infra.md", "docs/demo.md", "docs/results/demo-nd11-nd12.md",
                     "not a turnkey live demo", "no installed", "classifier decision computation"):
        assert required in text, required


def test_versioned_demo_report_retains_performance_denominators_and_source_ids():
    text = (ROOT / "docs/results/demo-nd11-nd12.md").read_text()
    for row in ("| Bill read |147 |13.115 |20.876 |379.438 |",
                "| Bill payment |282 |16.865 |24.637 |384.506 |",
                "| Extra transfer |280 |16.826 |24.179 |395.646 |",
                "| Profile read |137 |12.249 |19.985 |382.739 |",
                "| Profile update |237 |15.771 |23.843 |431.833 |",
                "| Qualification |86.826 |95.553 |433.469 |",
                "| Fresh rehearsal |96.255 |103.375 |421.112 |"):
        assert row in text
    for required in ("five unique", "14/14", "6 classifier and 3 LLM", "Startup appendix",
                     "f9391cedd2e348b6b7fd5e0aabb03c00", "85a0b42ce7e54bc3b3d9a56821d492a9",
                     "332 local /202 external", "conservative holds", "#17"):
        assert required in text
    assert "Below15ms" not in text and "native_core_below15" not in text
