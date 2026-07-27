#!/usr/bin/env python3
"""
Script to help fix DATABASE_URL by encoding special characters in password.
"""

from urllib.parse import quote, urlparse, urlunparse

def encode_database_url(url: str) -> str:
    """Encode special characters in the password part of DATABASE_URL."""
    parsed = urlparse(url)
    
    # Extract username and password
    if ':' in parsed.username or '@' in (parsed.password or ''):
        # If password contains special characters, encode them
        if parsed.password:
            # Encode the password part
            encoded_password = quote(parsed.password, safe='')
            # Reconstruct the netloc
            if parsed.username:
                netloc = f"{parsed.username}:{encoded_password}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
            else:
                netloc = parsed.netloc
        else:
            netloc = parsed.netloc
    else:
        netloc = parsed.netloc
    
    # Reconstruct URL
    fixed_url = urlunparse((
        parsed.scheme,
        netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment
    ))
    
    return fixed_url

if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE_URL Password Encoder")
    print("=" * 60)
    print()
    print("If your Supabase password contains special characters (@, #, etc.),")
    print("you need to URL-encode them in your DATABASE_URL.")
    print()
    
    # Get current DATABASE_URL from user
    current_url = input("Enter your current DATABASE_URL (or press Enter to skip): ").strip()
    
    if not current_url:
        print()
        print("Instructions:")
        print("1. Go to Supabase Dashboard → Settings → Database")
        print("2. Copy the 'Connection string' → 'URI' format")
        print("3. Paste it here, or update backend/.env directly")
        print()
        print("Example format:")
        print("postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres")
        return
    
    print()
    print("Original URL:")
    print(current_url)
    print()
    
    # Try to fix it
    try:
        fixed_url = encode_database_url(current_url)
        if fixed_url != current_url:
            print("Encoded URL (copy this to your .env file):")
            print(fixed_url)
        else:
            print("URL looks correct. No encoding needed.")
            print()
            print("If you still get connection errors:")
            print("1. Verify the URL from Supabase Dashboard")
            print("2. Make sure you're using the 'URI' format (not other formats)")
            print("3. Check that the hostname is correct")
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Manual fix:")
        print("1. Extract your password from the URL")
        print("2. Encode special characters:")
        print("   @ → %40")
        print("   # → %23")
        print("   : → %3A")
        print("   / → %2F")
        print("   % → %25")
        print("3. Replace the password in the URL with the encoded version")

