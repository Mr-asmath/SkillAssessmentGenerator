import google.generativeai as genai

genai.configure(api_key="AIzaSyBoiCnFfKwTfQLNhPJt6DUQLXcFw3OoaY0")

models = genai.list_models()  # or similar method
for m in models:
    print(m.name)
