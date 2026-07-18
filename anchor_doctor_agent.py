import argparse
import sys
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

SYSTEM_PROMPT = "You are the Anchor Diagnostic AI Agent. You must only output in ASCII characters. Do not use emojis, special unicode characters, or non-ASCII formatting. Provide clear, concise, diagnostic feedback."

def generate_response(prompt: str) -> str:
    # Use environment variable GEMINI_API_KEY if available.
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        genai.configure(api_key=api_key)
    
    # We use a standard fast model. The user can override via env var if they want.
    model_name = os.environ.get("DOCTOR_MODEL", "gemini-1.5-flash")
    
    try:
        model = genai.GenerativeModel(model_name, system_instruction=SYSTEM_PROMPT)
        
        # Ensure we don't block on safety for standard diagnostic reports
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        response = model.generate_content(
            prompt,
            safety_settings=safety_settings
        )
        return response.text
    except Exception as e:
        return f"Error connecting to AI diagnostic service: {e}"

def main():
    parser = argparse.ArgumentParser(description="Anchor Doctor Agent")
    parser.add_argument("--prompt", type=str, default="", help="The prompt to send to the AI agent")
    parser.add_argument("--init", action="store_true", help="Run initialization routine")
    args = parser.parse_args()
    
    if args.init:
        report_dir = os.path.join(os.path.dirname(__file__), "health_reports")
        report_text = "No recent health reports found."
        if os.path.exists(report_dir):
            reports = [f for f in os.listdir(report_dir) if f.endswith('.md') and f.lower() != 'readme.md']
            if reports:
                latest = max(reports)
                try:
                    with open(os.path.join(report_dir, latest), 'r', encoding='utf-8') as f:
                        report_text = f.read()
                except:
                    pass
        prompt = f"Summarize this health report in short bullet points for the user:\\n\\n{report_text}\\n\\nAppend this list of capabilities to the bottom:\\n- Run full system diagnostic (/api/doctor/run?cmd=healthcheck)\\n- Ask questions about the current health state."
    else:
        prompt = args.prompt.strip()
        if not prompt:
            prompt = "Perform a basic system greeting and inform the user that the Diagnostic AI Agent is ready."
        
    try:
        response_text = generate_response(prompt)
        print(response_text)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
