from typing import Any, Dict, List
from uuid import UUID
import re


def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def parse_file_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def calculate_grade(percentage: float) -> tuple[str, bool]:
    """Calculate grade based on percentage."""
    if percentage >= 90:
        return "A+", True
    elif percentage >= 80:
        return "A", True
    elif percentage >= 70:
        return "B", True
    elif percentage >= 60:
        return "C", True
    elif percentage >= 50:
        return "D", True
    else:
        return "F", False


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage."""
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:255 - len(ext) - 1] + '.' + ext if ext else name[:255]
    return filename


def paginate_response(items: List[Any], page: int, limit: int, total: int) -> Dict:
    """Create paginated response."""
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 0
    }

