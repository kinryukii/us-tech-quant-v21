"""Synthetic H10 syntax and publication gates; no true currency data."""
import hashlib
from pathlib import Path
import pytest
from scripts.research.a2.data.consensus_h10_fx_sources import parse_cad_h10_release


def edition(tmp_path, *, release="September 22, 2025", values="2 2 2 2 ND", labels="Sep. 15|Sep. 16|Sep. 17|Sep. 18|Sep. 19"):
    cells="".join("<th>"+x+"</th>" for x in ["COUNTRY","CURRENCY",*labels.split("|")])
    canada="<tr><th>CANADA</th><td>DOLLAR</td>"+"".join("<td>"+x+"</td>" for x in values.split())+"</tr>"
    # Poisoned unrelated currency cells must never reach a numeric decoder.
    raw=('<div class="dates">Release Date: '+release+'</div><div class="tableunit">(Rates in currency units per U.S. dollar except as noted by an asterisk)</div><table><thead><tr>'+cells+'</tr></thead>'+canada+'<tr><th>CHINA</th><td>DO_NOT_DECODE_OTHER_CURRENCY</td></tr></table>').encode()
    path=tmp_path/"synthetic_H10.html";path.write_bytes(raw)
    return path,hashlib.sha256(raw).hexdigest()


def test_cad_only_inverse_unit_bound_and_explicit_nd(tmp_path):
    p,sha=edition(tmp_path)
    d=parse_cad_h10_release(p,expected_sha256=sha,expected_release_date="2025-09-22")
    assert len(d["observations"])==4 and d["no_data_observation_dates"]==["2025-09-19"]
    assert d["available_at"]=="2025-09-23 03:59:59+00:00"
    assert d["quote_unit"]=="CAD_PER_USD" and d["usd_per_cad_rule"]=="1 / source CAD_PER_USD"
    assert d["other_currency_values_decoded"] is False and d["actual_publication_timestamp"]=="UNKNOWN_RETAINED"


def test_header_qualification_precedes_any_poison_rate_decode(tmp_path):
    p,sha=edition(tmp_path,release="January 5, 2026",values="NEVER_DECODE 1 1 1 1")
    with pytest.raises(ValueError,match="SOURCE_RELEASE_DATE_MISMATCH"):
        parse_cad_h10_release(p,expected_sha256=sha,expected_release_date="2025-09-22")
    with pytest.raises(ValueError,match="PRE2026_EXACT_RELEASE_DATE"):
        parse_cad_h10_release(p,expected_sha256=sha,expected_release_date="2026-01-05")


def test_causal_year_boundary_and_physical_sha_gate(tmp_path):
    p,sha=edition(tmp_path,release="January 6, 2025",values="2 2 ND 2 2",labels="Dec. 30|Dec. 31|Jan. 1|Jan. 2|Jan. 3")
    d=parse_cad_h10_release(p,expected_sha256=sha,expected_release_date="2025-01-06")
    assert [x["observation_date"] for x in d["observations"]]==["2024-12-30","2024-12-31","2025-01-02","2025-01-03"]
    with pytest.raises(ValueError,match="SOURCE_CHANGED"):
        parse_cad_h10_release(p,expected_sha256="f"*64,expected_release_date="2025-01-06")


def test_duplicate_canada_row_rejected_before_conflicting_rate_can_be_selected(tmp_path):
    p,_=edition(tmp_path)
    raw=p.read_bytes().replace(b"</table>",b"<tr><th>CANADA</th><td>DOLLAR</td><td>4</td><td>4</td><td>4</td><td>4</td><td>4</td></tr></table>")
    p.write_bytes(raw)
    with pytest.raises(ValueError,match="UNIQUE_EXACT_NONASTERISK"):
        parse_cad_h10_release(p,expected_sha256=hashlib.sha256(raw).hexdigest(),expected_release_date="2025-09-22")
