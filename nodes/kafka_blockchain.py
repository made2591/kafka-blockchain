import hashlib
from time import time

import sys
from pykafka import KafkaClient
from pykafka.common import OffsetType
import json
from uuid import uuid4

from flask import Flask, jsonify, request

TEST_KAFKA_BROKER = 'kafka:9092'
TX_GROUP = b'tx_group'
TX_TOPIC = b'transactions'
BLOCKCHAIN_TOPIC = b'blockchain'
BLOCKCHAIN_GROUP = b'blockchain_group'
NODES_TOPIC = b'nodes'
NODES_GROUP = b'nodes_group'


class KafkaBlockchain(object):

    def __init__(self, partition, name):
        self.blockchain = []
        self.current_transactions = []
        self.nodes = []
        self.node_identifier = str(uuid4()).replace('-', '')
        self.last_offset = 0
        self.partition = partition
        self.name = name

    def start(self):
        self.initialize_chain()
        self.read_and_validate_chain()
        self.read_transactions(self.partition)

    def initialize_chain(self):
        if self.find_highest_offset() == 0:
            self.publish_block(self.genesis_block())

    def presentation(self):
        topic = self.get_topic(NODES_TOPIC)
        producer = topic.get_producer()
        # Add the block to our internal representation, and publish it
        name_message = json.dumps({'name' : self.name})
        producer.produce(name_message.encode('utf-8'))
        self.last_offset += 1
        print(f"Presentation done with name {self.name}")
        return self.name

    def update_nodes_in_networks(self, offset=OffsetType.EARLIEST):
        topic = self.get_topic(NODES_TOPIC)
        consumer = topic.get_simple_consumer(
            consumer_group=NODES_GROUP,
            auto_commit_enable=True,
            auto_offset_reset=offset,
            reset_offset_on_start=True,
            consumer_timeout_ms=5000)

        for message in consumer:
            if message:
                print(message.value)
                try:
                    node = json.loads(message.value.decode('utf-8'))
                    if self.blockchain.name != node['name']:
                        self.nodes.append(node['name'])
                    self.last_offset = message.offset + 1
                except:
                    pass

    def read_and_validate_chain(self, offset=OffsetType.EARLIEST):
        topic = self.get_topic(BLOCKCHAIN_TOPIC)
        consumer = topic.get_simple_consumer(
            consumer_group=BLOCKCHAIN_GROUP,
            auto_commit_enable=True,
            auto_offset_reset=offset,
            reset_offset_on_start=True,
            consumer_timeout_ms=5000)

        for message in consumer:
            if message:
                block = json.loads(message.value.decode('utf-8'))
                # Skip validating the genesis block
                if message.offset == 0:
                    self.blockchain.append(block)
                elif self.valid_block(self.blockchain[-1], block):
                    self.blockchain.append(block)
                self.last_offset = message.offset + 1

    def read_transactions(self, partition):
        print(f'Waiting for transactions on partition {partition}')
        tx_count = 0
        topic = self.get_topic(TX_TOPIC)
        partition = topic.partitions[int(partition)]
        consumer = topic.get_simple_consumer(
            consumer_group=TX_GROUP,
            auto_commit_enable=True,
            auto_offset_reset=OffsetType.LATEST,
            partitions=[partition])

        try:
            for message in consumer:
                if message is not None:
                    tx_count += 1
                    transaction = message.value.decode('utf-8')
                    print(transaction)
                    new_tx = json.loads(transaction)
                    self.new_transaction(
                        sender=new_tx['from'],
                        recipient=new_tx['to'],
                        amount=new_tx['amount'],
                    )
                    # Create a new block every 3 transactions
                    if len(self.current_transactions) >= 3:
                        self.mine()
                        self.current_transactions = []

        except Exception as ex:
            consumer.stop()
            print(ex)

    def mine(self):
        # First check if there's a new block available with a higher offset
        # than our internal copy. If so, rewind our offset and consume from
        # that offset to get latest changes checking that the newest additions
        # are valid blocks, and adding to our internal representation if so
        latest_offset = self.find_highest_offset()
        if self.find_highest_offset() > self.last_offset:
            print('New blocks found, appending to our chain')
            self.read_and_validate_chain(latest_offset)

            # Now we've achieved consensus, continue with adding our transactions
            # and making a new block.
            # First, run the proof of work algorithm to get the next proof
            last_proof = self.blockchain[-1]['proof']
            proof = self.proof_of_work(last_proof)

            # Reward ourselves for finding the proof with a new transaction
            self.new_transaction(
                sender="0",
                recipient=self.node_identifier,
                amount=1,
            )

            # Publish the new block to add it to the chain
            block = self.new_block(proof)
            self.publish_block(block)
            return block
        else:
            return None

    def get_topic(self, topic_name):
        client = KafkaClient(TEST_KAFKA_BROKER)
        return client.topics[topic_name]

    def publish_block(self, block):
        topic = self.get_topic(BLOCKCHAIN_TOPIC)
        producer = topic.get_producer()
        # Add the block to our internal representation, and publish it
        self.blockchain.append(block)
        producer.produce(json.dumps(block).encode('utf-8'))
        self.last_offset += 1
        print(f"Published block with proof {block['proof']}")
        return block['proof']

    def find_highest_offset(self):
        latest = self.get_topic(BLOCKCHAIN_TOPIC).latest_available_offsets()
        # TODO: We are only using topic partition 0 at this point
        return latest[0].offset[0]

    def genesis_block(self):
        return {
            'index': 1,
            'timestamp': time(),
            'transactions': [],
            'proof': 100,
            'previous_hash': 1,
        }

    def new_block(self, proof):
        """
        Create a new Block in the Blockchain
        :param proof: <int> The proof given by the Proof of Work algorithm
        :param previous_hash: (Optional) <str> Hash of previous Block
        :return: <dict> New Block
        """
        previous_hash = self.hash(self.blockchain[-1])

        block = {
            'index': len(self.blockchain) + 1,
            'timestamp': time(),
            'transactions': self.current_transactions,
            'proof': proof,
            'previous_hash': previous_hash
        }

        return block

    def new_transaction(self, sender, recipient, amount):
        self.current_transactions.append({
            'sender': sender,
            'recipient': recipient,
            'amount': amount,
        })

    def proof_of_work(self, last_proof):
        """
        Simple Proof of Work Algorithm:
         - Find a number p' such that hash(pp') contains leading 4 zeroes, where p is the previous p'
         - p is the previous proof, and p' is the new proof
        :param last_proof: <int>
        :return: <int>
        """

        proof = 0
        while self.valid_proof(last_proof, proof) is False:
            proof += 1

        return proof

    def valid_proof(self, last_proof, proof):
        """
        Validates the Proof: Does hash(last_proof, proof) contain 4 leading zeroes?
        :param last_proof: <int> Previous Proof
        :param proof: <int> Current Proof
        :return: <bool> True if correct, False if not.
        """
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()

        return guess_hash[:4] == "0000"

    def hash(self, block):
        """
        Creates a SHA-256 hash of a Block
        :param block: <dict> Block
        :return: <str>
        """
        # We must make sure that the Dictionary is Ordered, or we'll have
        # inconsistent hashes
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def valid_block(self, last_block, block):
        # Check each block, add to our local copy if it's valid
        if block['previous_hash'] != self.hash(last_block):
            return False

        # Check that the Proof of Work is correct
        if not self.valid_proof(last_block['proof'], block['proof']):
            return False
        return True


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit('Please supply a port, partition id and a name')

    blockchain = KafkaBlockchain(sys.argv[2], sys.argv[3])

    # Instantiate our Node
    app = Flask(__name__)

    # Generate a globally unique address for this node
    node_identifier = str(uuid4()).replace('-', '')

    # We'll mine a new Block
    @app.route('/mine', methods=['GET'])
    def mine():

        block = blockchain.mine()
        if block != None:
            response = {
                'message': "New Block Forged",
                'index': block['index'],
                'transactions': block['transactions'],
                'proof': block['proof'],
                'previous_hash': block['previous_hash'],
            }
            return jsonify(response), 200
        else:
            response = {
                'message': 'No new block to be mined',
            }
            return jsonify(response), 200
      
    # We'll add a new transaction
    @app.route('/transactions/new', methods=['POST'])
    def new_transaction():
        values = request.get_json()

        # Check that the required fields are in the POST'ed data
        required = ['sender', 'recipient', 'amount']
        if not all(k in values for k in required):
            return 'Missing values', 400

        # Create a new Transaction
        index = blockchain.new_transaction(values['sender'], values['recipient'], values['amount'])

        response = {'message': f'Transaction will be added to Block {index}'}
        return jsonify(response), 201

    @app.route('/chain', methods=['GET'])
    def full_chain():
        blockchain.read_and_validate_chain()
        response = {
            'chain': blockchain.blockchain,
            'length': len(blockchain.blockchain),
        }
        return jsonify(response), 200

    @app.route('/nodes/register', methods=['POST'])
    def register_nodes():
        values = request.get_json()

        node = values.get('node')
        if node is None:
            return "Error: Please supply a valid node", 400

        blockchain.presentation(node)
        blockchain.update_nodes_in_networks()

        response = {
            'message': 'Presented to networks',
            'total_nodes': list(blockchain.nodes),
        }
        return jsonify(response), 201

    @app.route('/nodes/update', methods=['GET'])
    def consensus():
        blockchain.update_nodes_in_networks()

        response = {
            'message': 'Nodes updated',
            'new_chain': blockchain.nodes
        }

        return jsonify(response), 200

    blockchain.presentation()
    blockchain.update_nodes_in_networks()
    blockchain.read_and_validate_chain()
    app.run(host='0.0.0.0', port=int(sys.argv[1]))


