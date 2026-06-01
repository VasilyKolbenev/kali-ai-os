import sys
import asyncio
import uvicorn

if __name__ == "__main__":
    # Fix for Uvicorn on Windows: Uvicorn explicitly sets WindowsSelectorEventLoopPolicy,
    # which breaks asyncio subprocesses (used by native agents).
    # We must force ProactorEventLoopPolicy.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        # Monkey-patch uvicorn to prevent it from overriding our policy
        try:
            import uvicorn.loops.asyncio
            uvicorn.loops.asyncio.setup = lambda: None
        except ImportError:
            pass

    print("Starting KALI server with ProactorEventLoop (Subprocess support enabled)...")
    uvicorn.run(
        "kernel.main:create_app", 
        host="127.0.0.1", 
        port=3005, 
        reload=False,
        factory=True
    )
