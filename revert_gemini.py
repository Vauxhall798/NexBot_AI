import sys

with open("main.py", "r") as f:
    content = f.read()

content = content.replace("OPENROUTER_API_KEY", "GEMINI_API_KEY")
content = content.replace("OPENROUTER_MODEL", "GEMINI_MODEL")
content = content.replace("(OpenRouter)", "(Gemini)")
content = content.replace("Router Key", "Gemini Key")
content = content.replace("OpenRouter ready!", "Gemini ready!")
content = content.replace("OpenRouter API Error", "Gemini API Error")
content = content.replace("OpenRouter API error", "Gemini API error")
content = content.replace("OpenRouter Fallback", "Gemini Fallback")
content = content.replace("OpenRouter Free models", "Gemini models")
content = content.replace("OpenRouter not ready", "Gemini not ready")

with open("main.py", "w") as f:
    f.write(content)

print("Variables renamed successfully.")
