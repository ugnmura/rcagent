"""Tools that curate the template catalog."""

from serenedb_extractor import format as fmt
from serenedb_extractor.context import AppContext


def rename_parameter(ctx: AppContext, log_table: str, template: str, old_name: str, new_name: str) -> str:
    lt = ctx.store.get_log_table(log_table)
    resolved = ctx.store.rename_parameter(lt.name, template, old_name, new_name)
    t = resolved.template
    out = [
        fmt.how_measured("catalog updated; no log data was read and no entries were changed"),
    ]
    if resolved.redirected_from:
        out.append(f"{resolved.redirected_from} was merged into {t.template_id}; renamed there.")
    names = ", ".join(f"{p.name} ({p.kind})" for p in t.params)
    out.append(f"{t.template_id}  {fmt.template_text(t.template)}")
    out.append(f"Parameter '{old_name}' is now '{new_name}' for good; later surveys keep the name. Parameters: {names}.")
    return "\n".join(out)
