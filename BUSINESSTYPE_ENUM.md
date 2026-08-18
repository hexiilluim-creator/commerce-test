# BusinessType Enum Values
- Available: APPOINTMENTS, ECOMMERCE, HYBRID
- Missing: AUTO, AUTO_PARTS (not in the enum)
- The enum is StrEnum with string values: "auto", "beauty", "legal", etc.
- The enum members that exist in the code but not as class attributes: AUTO
- In database.py line 604: AUTO = "auto" is defined but the import doesn't expose it
- The enum is imported from models.database
