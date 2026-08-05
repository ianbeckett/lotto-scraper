"""
Offline sanity test for scraper.parse_price_page / _build_game_record.

The sandbox this was built in cannot reach walottery.com directly (outbound
proxy allowlist blocks it), so this test uses a hand-built HTML snippet that
mirrors the real page's structure and content, based on data actually
retrieved from https://walottery.com/Scratch/TopPrizesRemaining.aspx?price=$1
on 2026-08-05 (games LUCKY DOG DOUBLER #2005 and "2026" #1991). It checks
that the parser recovers the right games, tiers, and derived metrics from
that structure, and specifically exercises the "top prize already exhausted"
case (game 1991, $2,026 tier: 4 total / 4 paid / 0 remaining) and the
"no last day to redeem" case (game 2005).

This is NOT a substitute for testing against the live site - if WA Lottery
changes their markup, this test won't catch it. Run the app and click
"Refresh Data" to confirm it works against the real site.
"""

import scraper

MOCK_HTML = """
<html><body>
<div class="game-block">
  <a href="https://walottery.com/Scratch/Explorer.aspx?id=2005"><img src="grid/2005.jpg" alt="LUCKY DOG DOUBLER"></a>
  <a href="https://walottery.com/Scratch/Explorer.aspx?id=2005">LUCKY DOG DOUBLER</a>
  <p>$1 | 2005</p>
  <table>
    <tr><th>Prize Amount</th><th>Total Prizes</th><th>Prizes Paid</th><th>Prizes Remaining</th></tr>
    <tr><td>$2,000</td><td>4</td><td>3</td><td>1</td></tr>
    <tr><td>$100</td><td>93</td><td>44</td><td>49</td></tr>
    <tr><td>$50</td><td>224</td><td>111</td><td>113</td></tr>
    <tr><td>$1</td><td>346,182</td><td>152,237</td><td>193,945</td></tr>
  </table>
</div>
<div class="game-block">
  <a href="https://walottery.com/Scratch/Explorer.aspx?id=1991"><img src="grid/1991.jpg" alt="2026"></a>
  <a href="https://walottery.com/Scratch/Explorer.aspx?id=1991">2026</a>
  <p>$1 | 1991</p>
  <p>Last Day To Redeem: 08/11/26</p>
  <table>
    <tr><th>Prize Amount</th><th>Total Prizes</th><th>Prizes Paid</th><th>Prizes Remaining</th></tr>
    <tr><td>$2,026</td><td>4</td><td>4</td><td>0</td></tr>
    <tr><td>$100</td><td>56</td><td>47</td><td>9</td></tr>
    <tr><td>$1</td><td>154,015</td><td>98,941</td><td>55,074</td></tr>
  </table>
</div>
</body></html>
"""


def main():
    games = scraper.parse_price_page(MOCK_HTML, "$1")
    assert len(games) == 2, f"expected 2 games, got {len(games)}: {[g['name'] for g in games]}"

    by_id = {g["id"]: g for g in games}

    g1 = by_id["2005"]
    assert g1["name"] == "LUCKY DOG DOUBLER"
    assert g1["price"] == "$1"
    assert g1["game_number"] == "2005"
    assert g1["last_day_to_redeem"] is None, "2005 should have no redeem date"
    assert g1["top_prize_amount"] == 2000
    assert g1["top_prize_total"] == 4
    assert g1["top_prize_remaining"] == 1
    assert g1["top_prize_pct_remaining"] == 25.0
    assert g1["total_prizes_total"] == 4 + 93 + 224 + 346182
    assert g1["total_prizes_remaining"] == 1 + 49 + 113 + 193945
    # remaining cash value = 2000*1 + 100*49 + 50*113 + 1*193945
    expected_cash = 2000 * 1 + 100 * 49 + 50 * 113 + 1 * 193945
    assert g1["remaining_cash_value"] == expected_cash, (g1["remaining_cash_value"], expected_cash)

    g2 = by_id["1991"]
    assert g2["name"] == "2026"
    assert g2["last_day_to_redeem"] == "08/11/26"
    assert g2["top_prize_amount"] == 2026
    assert g2["top_prize_remaining"] == 0
    assert g2["top_prize_pct_remaining"] == 0.0, "exhausted top prize should show 0%, not None/error"

    print("All assertions passed.")
    print(f"Parsed {len(games)} games:")
    for g in games:
        print(f"  #{g['id']} {g['name']}: top prize {g['top_prize_remaining']}/{g['top_prize_total']} "
              f"({g['top_prize_pct_remaining']}% left), remaining cash value ${g['remaining_cash_value']:,}")


if __name__ == "__main__":
    main()
