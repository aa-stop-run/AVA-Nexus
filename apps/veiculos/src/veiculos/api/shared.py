import pathlib
from decimal import Decimal
from fastapi.templating import Jinja2Templates

# Procura o diretório de templates com resolução robusta
_pkg_templates = pathlib.Path(__file__).resolve().parent.parent / "templates"
_local_templates = pathlib.Path("src/veiculos/templates")
_app_templates = pathlib.Path("/app/src/veiculos/templates")

if _app_templates.exists():
    templates_dir = _app_templates
elif _local_templates.exists():
    templates_dir = _local_templates
else:
    templates_dir = _pkg_templates

templates = Jinja2Templates(directory=str(templates_dir))


def format_pt(valor: Decimal | float | int | None) -> str:
    if valor is None:
        return "0,00"
    try:
        val = Decimal(str(valor))
        # Formata com separador de milhares '.' e decimal ','
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor)


templates.env.filters["format_pt"] = format_pt
