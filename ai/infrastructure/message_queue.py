import logging

logger = logging.getLogger("agent_infrastructure.mq")

class MessageQueueStub:
    """Stub cho RabbitMQ / Redis Streams hỗ trợ xử lý tác vụ nền bất đồng bộ"""
    def __init__(self):
        logger.info("Message Queue Stub initialized (Ready for Async Task Broker)")

    async def publish(self, queue_name: str, message: dict):
        logger.info(f"[MQ Stub] Published message to {queue_name}: {message}")
        return True

mq = MessageQueueStub()