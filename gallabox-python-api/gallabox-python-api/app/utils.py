def error_detail(error: Exception) -> dict:
    message = str(error).strip() or error.__class__.__name__
    return {
        "message": message,
        "errorType": error.__class__.__name__
    }
