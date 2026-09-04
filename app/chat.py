"""Callable client for making Gemini API requests."""

import os
from typing import Any, Optional

from google import genai


class LLM:
	"""A small object-oriented client for Gemini's free API tier."""

	def __init__(
		self,
		api_key: Optional[str] = None,
		model: str = "gemini-3.5-flash-lite",
	) -> None:
		key = api_key or os.getenv("GEMINI_API_KEY")
		if not key:
			raise ValueError("Provide api_key or set the GEMINI_API_KEY environment variable.")

		self.client = genai.Client(api_key=key)
		self.model = model

	def __call__(self, prompt: str, **kwargs: Any) -> str:
		"""Send ``prompt`` to Gemini and return the generated text."""
		# Fetch and print the available model IDs
		# for model in self.client.models.list():
		# 	print(model.name)
		chat = self.client.chats.create(model=self.model)
		response = chat.send_message(prompt, **kwargs)
		return response.text


__all__ = ["LLM"]
