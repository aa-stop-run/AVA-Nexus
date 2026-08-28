import pathlib
from decimal import Decimal
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def format_moeda(valor: Decimal | float | int | None) -> str:
    if valor is None:
        return "€ 0,00"
    try:
        val = float(valor)
        sinal = "-" if val < 0 else ""
        abs_val = abs(val)
        fmt = f"{abs_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", " ")
        return f"{sinal}€ {fmt}"
    except Exception:
        return str(valor)


def format_data_pt(data_val) -> str:
    if not data_val:
        return "—"
    try:
        if hasattr(data_val, "strftime"):
            return data_val.strftime("%d/%m/%Y")
        return str(data_val)
    except Exception:
        return str(data_val)


templates.env.filters["moeda"] = format_moeda
templates.env.filters["data_pt"] = format_data_pt
