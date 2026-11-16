"""Draw docs/architecture-aws.{en,fr}.svg (hand-laid SVG, no dependencies).

Usage: python scripts/gen_architecture_diagram.py
PNG copies (for slides and the video): open each SVG in a browser and screenshot it, e.g.
msedge --headless --window-size=1280,1120 --screenshot=docs/architecture-aws.en.png docs/architecture-aws.en.svg
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs"

T = {
    "en": dict(
        title="AlphaForge AI — AWS architecture",
        sub="Every LLM call goes through Amazon Bedrock · region us-east-1",
        user="User", user2="browser",
        app="Application — AWS Workshop Studio (us-east-1)", aws="AWS services — us-east-1",
        ui="React + Vite web app", ui2="EN / FR · persona picker, chat, trace panel",
        api="FastAPI backend", api2="REST + WebSocket · pipeline.py",
        router="Intent router", router2="rules, then Haiku: chat reply or analysis?",
        boss="Boss agent (Strands)", boss2="picks tools, builds the plan",
        work="Python workers — no LLM", work2="risk · 2022 stress test · market cycle",
        work3="suitability · comparisons",
        rev="Reviewer (deterministic)", rev2="sources, periods, limits, no look-ahead",
        pres="Presenter", pres2="writes the answer from worker results only",
        trace="Run trace (every step)",
        gr="Amazon Bedrock Guardrails", gr2="ApplyGuardrail: advice, trades, PII, attacks",
        haiku="Amazon Bedrock · Converse", haiku2="Claude Haiku 4.5 (global. profile)",
        haiku3="router + boss",
        s3="Amazon S3", s3a="data/  prices, FX, macro CSVs", s3b="runs/  JSON trace of each answer",
        sonnet="Amazon Bedrock · ConverseStream", sonnet2="Claude Sonnet 4.6, streamed",
        fred="FRED (public macro data)", fred2="fetch_fred_extra.py",
        a_user="question", a_gr="check question, answer, chat reply",
        a_route="intent + chat reply", a_haiku="plan + tool calls", a_s3r="read data", a_s3w="save trace",
        a_sonnet="answer, streamed", a_analysis="analysis", a_tools="tool calls (parallel)", a_res="results",
        a_pass="pass", a_fail="fail → retry (max 2)", a_back="streamed answer", a_chat="chat reply",
        a_fred="upload",
        lg_llm="LLM step (Bedrock)", lg_det="Deterministic Python", lg_aws="AWS service",
        lg_app="Application",
    ),
    "fr": dict(
        title="AlphaForge AI — Architecture AWS",
        sub="Tous les appels LLM passent par Amazon Bedrock · région us-east-1",
        user="Utilisateur", user2="navigateur",
        app="Application — AWS Workshop Studio (us-east-1)", aws="Services AWS — us-east-1",
        ui="Application web React + Vite", ui2="EN / FR · choix du persona, clavardage, trace",
        api="Backend FastAPI", api2="REST + WebSocket · pipeline.py",
        router="Routeur d’intention", router2="règles, puis Haiku : réponse directe ou analyse?",
        boss="Agent patron (Strands)", boss2="choisit les outils, bâtit le plan",
        work="Travailleurs Python — sans LLM", work2="risque · test de stress 2022 · cycle",
        work3="conformité · comparaisons",
        rev="Réviseur (déterministe)", rev2="sources, périodes, limites, pas d'anticipation",
        pres="Présentateur", pres2="rédige à partir des seuls résultats",
        trace="Trace d'exécution",
        gr="Amazon Bedrock Guardrails", gr2="ApplyGuardrail : conseil, transactions, PII",
        haiku="Amazon Bedrock · Converse", haiku2="Claude Haiku 4.5 (profil global.)",
        haiku3="routeur + patron",
        s3="Amazon S3", s3a="data/  CSV prix, FX, macro", s3b="runs/  trace JSON de chaque réponse",
        sonnet="Amazon Bedrock · ConverseStream", sonnet2="Claude Sonnet 4.6, en continu",
        fred="FRED (données macro publiques)", fred2="fetch_fred_extra.py",
        a_user="question", a_gr="filtre question, réponse, réponse directe",
        a_route="intention + réponse directe", a_haiku="plan + appels d'outils", a_s3r="lecture des données",
        a_s3w="sauvegarde trace", a_sonnet="réponse en continu", a_analysis="analyse",
        a_tools="appels d'outils (parallèles)", a_res="résultats", a_pass="réussite",
        a_fail="échec → reprise (max 2)", a_back="réponse en continu", a_chat="réponse directe",
        a_fred="téléversement",
        lg_llm="Étape LLM (Bedrock)", lg_det="Python déterministe", lg_aws="Service AWS",
        lg_app="Application",
    ),
}

C = dict(ink="#1f2933", muted="#52606d", line="#7b8794", app="#eef2f7", appb="#9aa5b1",
         llm="#efe7fb", llmb="#7c4dcc", det="#e6f4ea", detb="#2f8f4e", aws="#fff4e5", awsb="#e07b00")
W_, H_ = 1280, 1120


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def box(x, y, w, h, fill, stroke, lines):
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>']
    y0 = y + h / 2 - (len(lines) - 1) * 9
    for i, t in enumerate(lines):
        weight, size, col = ("700", 15, C["ink"]) if i == 0 else ("400", 12.5, C["muted"])
        out.append(f'<text x="{x + w / 2}" y="{y0 + i * 18 + 5}" text-anchor="middle" font-size="{size}" '
                   f'font-weight="{weight}" fill="{col}">{esc(t)}</text>')
    return "\n".join(out)


def arrow(d, label=None, lx=0, ly=0, dashed=False, both=False, rotate=False):
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    start = ' marker-start="url(#ah)"' if both else ""
    out = [f'<path d="{d}" fill="none" stroke="{C["line"]}" stroke-width="1.8"{dash}{start} marker-end="url(#ah)"/>']
    if label:
        rot = f' transform="rotate(-90 {lx} {ly})"' if rotate else ""
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="12" fill="{C["muted"]}"'
                   f' paint-order="stroke" stroke="#ffffff" stroke-width="4"{rot}>{esc(label)}</text>')
    return "\n".join(out)


def svg(t):
    L, R, W = 260, 560, 300   # app column
    AX, AW = 900, 310          # AWS column
    rows = dict(ui=(125, 70), api=(245, 70), router=(365, 70), boss=(485, 70), work=(600, 100),
                rev=(745, 70), pres=(865, 70))
    cy = {k: y + h / 2 for k, (y, h) in rows.items()}
    bot = {k: y + h for k, (y, h) in rows.items()}

    def app_box(k, fill, stroke, keys):
        return box(L, rows[k][0], W, rows[k][1], fill, stroke, [t[x] for x in keys])

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_}" height="{H_}" viewBox="0 0 {W_} {H_}" '
         f'font-family="Segoe UI, Helvetica, Arial, sans-serif">',
         '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
         f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{C["line"]}"/></marker></defs>',
         f'<rect width="{W_}" height="{H_}" fill="#ffffff"/>',
         f'<text x="640" y="42" text-anchor="middle" font-size="24" font-weight="700" fill="{C["ink"]}">{esc(t["title"])}</text>',
         f'<text x="640" y="68" text-anchor="middle" font-size="14" fill="{C["muted"]}">{esc(t["sub"])}</text>',
         f'<rect x="180" y="92" width="640" height="868" rx="14" fill="none" stroke="{C["appb"]}" stroke-width="1.5" stroke-dasharray="8 6"/>',
         f'<text x="196" y="112" font-size="13" font-weight="600" fill="{C["muted"]}">{esc(t["app"])}</text>',
         f'<rect x="860" y="212" width="390" height="748" rx="14" fill="#fffaf2" stroke="{C["awsb"]}" stroke-width="1.5" stroke-dasharray="8 6"/>',
         f'<text x="876" y="232" font-size="13" font-weight="600" fill="{C["awsb"]}">{esc(t["aws"])}</text>',
         box(20, 125, 130, 70, "#ffffff", C["ink"], [t["user"], t["user2"]]),
         app_box("ui", C["app"], C["appb"], ["ui", "ui2"]),
         app_box("api", C["app"], C["appb"], ["api", "api2"]),
         app_box("router", C["llm"], C["llmb"], ["router", "router2"]),
         app_box("boss", C["llm"], C["llmb"], ["boss", "boss2"]),
         app_box("work", C["det"], C["detb"], ["work", "work2", "work3"]),
         app_box("rev", C["det"], C["detb"], ["rev", "rev2"]),
         app_box("pres", C["llm"], C["llmb"], ["pres", "pres2"]),
         box(600, 718, 200, 34, "#ffffff", C["appb"], [t["trace"]]),
         box(AX, rows["api"][0], AW, 70, C["aws"], C["awsb"], [t["gr"], t["gr2"]]),
         box(AX, rows["router"][0], AW, bot["boss"] - rows["router"][0], C["aws"], C["awsb"],
             [t["haiku"], t["haiku2"], t["haiku3"]]),
         box(AX, rows["work"][0], AW, 130, C["aws"], C["awsb"], [t["s3"], t["s3a"], t["s3b"]]),
         box(AX, rows["pres"][0], AW, 70, C["aws"], C["awsb"], [t["sonnet"], t["sonnet2"]]),
         box(AX, 990, AW, 60, "#ffffff", C["line"], [t["fred"], t["fred2"]]),
         # flows inside the app
         arrow(f"M150,{cy['ui']} H{L - 2}", t["a_user"], 205, cy["ui"] - 8),
         arrow(f"M410,{bot['ui']} V{rows['api'][0] - 2}", both=True),
         arrow(f"M410,{bot['api']} V{rows['router'][0] - 2}"),
         arrow(f"M410,{bot['router']} V{rows['boss'][0] - 2}", t["a_analysis"], 450, 466),
         arrow(f"M410,{bot['boss']} V{rows['work'][0] - 2}", t["a_tools"], 500, 582),
         arrow(f"M410,{bot['work']} V{rows['rev'][0] - 2}", t["a_res"], 450, 726),
         arrow(f"M410,{bot['rev']} V{rows['pres'][0] - 2}", t["a_pass"], 445, 846),
         arrow(f"M{L},{cy['rev']} H238 V{cy['boss']} H{L - 2}", t["a_fail"], 232, (cy["boss"] + cy["rev"]) / 2, rotate=True),
         arrow(f"M{L},{cy['router']} H220 V{cy['api'] + 14} H{L - 2}", t["a_chat"], 214, (cy["api"] + cy["router"]) / 2 + 7, rotate=True),
         arrow(f"M{L},{cy['pres']} H198 V{cy['api'] - 14} H{L - 2}", t["a_back"], 192, (cy["boss"] + cy["rev"]) / 2, rotate=True),
         # flows to AWS
         arrow(f"M{R},{cy['api']} H{AX - 2}", t["a_gr"], 730, cy["api"] - 8, both=True),
         arrow(f"M{R},{cy['router']} H{AX - 2}", t["a_route"], 730, cy["router"] - 8, both=True),
         arrow(f"M{R},{cy['boss']} H{AX - 2}", t["a_haiku"], 730, cy["boss"] - 8, both=True),
         arrow(f"M{AX},635 H{R + 2}", t["a_s3r"], 730, 627),
         arrow(f"M800,735 H850 V705 H{AX - 2}", t["a_s3w"], 850, 768),
         arrow(f"M{R},{cy['pres']} H{AX - 2}", t["a_sonnet"], 730, cy["pres"] - 8, both=True),
         arrow(f"M{AX + AW},1020 H1232 V665 H{AX + AW + 2}", t["a_fred"], 1232, 840, dashed=True, rotate=True),
         ]
    lx = 180
    for fill, stroke, key in [(C["llm"], C["llmb"], "lg_llm"), (C["det"], C["detb"], "lg_det"),
                              (C["aws"], C["awsb"], "lg_aws"), (C["app"], C["appb"], "lg_app")]:
        p.append(f'<rect x="{lx}" y="1078" width="22" height="16" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        p.append(f'<text x="{lx + 30}" y="1091" font-size="13" fill="{C["ink"]}">{esc(t[key])}</text>')
        lx += 200
    p.append("</svg>")
    return "\n".join(p)


if __name__ == "__main__":
    for lang, t in T.items():
        (OUT / f"architecture-aws.{lang}.svg").write_text(svg(t), encoding="utf-8")
    print("wrote", ", ".join(f"docs/architecture-aws.{l}.svg" for l in T))
