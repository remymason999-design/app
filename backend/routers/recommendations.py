"""Recommendations router: AI explain."""
import os
from fastapi import APIRouter, Depends, HTTPException

from emergentintegrations.llm.chat import LlmChat, UserMessage

from core import require_user, find_movie, movies_by_ids, ExplainIn, logger

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("/explain")
async def explain(payload: ExplainIn, user: dict = Depends(require_user)):
    movie = find_movie(payload.movie_id)
    if not movie:
        raise HTTPException(404, "Movie not found")
    saved_titles = [m["title"] for m in movies_by_ids((user.get("saved") or [])[:5])]
    watched_titles = [m["title"] for m in movies_by_ids((user.get("watched") or [])[:5])]
    user_genres = user.get("genres") or []

    system = (
        "You are WatchSmart, a sharp, friendly streaming concierge. "
        "Write a single concise paragraph (max 55 words) explaining why a specific movie/show "
        "matches the user's taste. Reference the user's preferred genres and recent activity if relevant. "
        "Be specific, never generic. Never use bullet points or markdown."
    )
    prompt = (
        f"Movie: {movie['title']} ({movie['year']})\n"
        f"Genres: {', '.join(movie.get('genres', []))}\n"
        f"Synopsis: {movie['overview']}\n"
        f"User favorite genres: {', '.join(user_genres) or 'unspecified'}\n"
        f"Recently saved: {', '.join(saved_titles) or 'none'}\n"
        f"Recently watched: {', '.join(watched_titles) or 'none'}\n"
        "Write the explanation now."
    )
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return {"explanation": f"You'll likely enjoy {movie['title']} because it leans into {', '.join(movie.get('genres', [])[:2])} — a strong match for your taste."}
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"explain_{user['user_id']}_{movie['id']}",
            system_message=system,
        ).with_model("openai", "gpt-5.2")
        text = await chat.send_message(UserMessage(text=prompt))
        return {"explanation": text.strip()}
    except Exception as e:
        logger.warning(f"GPT-5.2 failed, falling back to Claude: {e}")
        try:
            chat = LlmChat(
                api_key=api_key,
                session_id=f"explain_{user['user_id']}_{movie['id']}",
                system_message=system,
            ).with_model("anthropic", "claude-sonnet-4-5-20250929")
            text = await chat.send_message(UserMessage(text=prompt))
            return {"explanation": text.strip()}
        except Exception as e2:
            logger.error(f"Both LLMs failed: {e2}")
            return {"explanation": f"You'll likely enjoy {movie['title']} because it leans into {', '.join(movie.get('genres', [])[:2])} — a strong match for your taste."}
