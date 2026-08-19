from pathlib import Path

source_path = Path(__file__).with_name("run_hardened_v3.py")
source = source_path.read_text()
old = 'condition=models.Q(("offset__isnull", False), ("partition__isnull", False), ("topic__gt", "")),'
new = 'condition=models.Q(("topic__gt", ""), ("partition__isnull", False), ("offset__isnull", False)),'
if source.count(old) != 1:
    raise RuntimeError("Expected exactly one hardened migration condition to normalize")
source = source.replace(old, new, 1)
exec(compile(source, str(source_path), "exec"), {"__name__": "__main__", "__file__": str(source_path)})
