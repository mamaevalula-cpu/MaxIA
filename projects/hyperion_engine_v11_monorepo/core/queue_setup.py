
import pika, sys
try:
    conn = pika.BlockingConnection(pika.ConnectionParameters('localhost', heartbeat=30))
    ch = conn.channel()
    ch.exchange_declare('hyperion.v12.core', exchange_type='topic', durable=True)
    ch.exchange_declare('hyperion.v12.dlx', exchange_type='direct', durable=True)
    queues = [
        ('hyperion.queue.received',   'task.lifecycle.received',      'dlq.system.ingest'),
        ('hyperion.queue.valuated',   'task.lifecycle.valuated',      'dlq.system.economic'),
        ('hyperion.queue.dispatch',   'task.capability.run',          'dlq.execution.retry'),
        ('hyperion.queue.validation', 'task.lifecycle.executed',      'dlq.quality.failed'),
        ('hyperion.queue.evolution',  'capability.evolution.trigger', 'dlq.evolution.failed'),
    ]
    for name, rkey, dlq in queues:
        ch.queue_declare(name, durable=True, arguments={
            'x-dead-letter-exchange': 'hyperion.v12.dlx',
            'x-dead-letter-routing-key': dlq,
            'x-message-ttl': 3600000
        })
        ch.queue_bind(name, 'hyperion.v12.core', rkey)
        dlq_q = dlq.replace('.', '_')
        ch.queue_declare(dlq_q, durable=True)
        ch.queue_bind(dlq_q, 'hyperion.v12.dlx', dlq)
        print(f'  Queue OK: {name}')
    conn.close()
    print('RabbitMQ setup complete')
except Exception as e:
    print(f'RMQ error: {e}')
    sys.exit(1)
