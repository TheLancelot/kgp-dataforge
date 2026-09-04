from chat import LLM
from dotenv import load_dotenv
load_dotenv("../.env")
llm = LLM()

def main() -> None:
	prompt = input("Prompt: ")
	response = llm(prompt)
	print(response)


if __name__ == "__main__":
	main()
