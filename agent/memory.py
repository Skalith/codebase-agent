from agent.paths import CHECKPOINT_DB_PATH

try:
    from langgraph.checkpoint.sqlite import SqliteSaver

    _cm = SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH)
    memory_checkpointer = _cm.__enter__()
    _persistent = True
except Exception:
    from langgraph.checkpoint.memory import MemorySaver

    memory_checkpointer = MemorySaver()
    _persistent = False
