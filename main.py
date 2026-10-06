"""
Simple test script to verify Gemini setup.

This script makes a single call to Gemini via GCP's Agent Platform API to confirm that:
- Your gcloud authentication is working
- Your project and billing are configured correctly
- The Agent Platform API is enabled
- Your Python environment can call Gemini models

No .env file needed - LiteLLM uses your gcloud configuration automatically.
"""

from litellm import completion

# Make a simple request to Gemini
# LiteLLM will use your Application Default Credentials and gcloud project config
response = completion(
    model="vertex_ai/gemini-3.5-flash-lite",
    vertex_location="global",
    messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
)

# Print the response
print(f"Response: {response.choices[0].message.content}")
print("\n✓ Success! Your Gemini setup is working correctly.")
