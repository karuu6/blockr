from crypto import *
import threading
import socket
import struct
import time
import json
import uuid
import ast
import sys
import os


class Peer(threading.Thread):
	def __init__(self, host, port, dataDir='storage', maxpeers=100, maxfilesize=10*(10**10), maxnumfiles=200):
		super(Peer,self).__init__()
		self.host     = host
		self.port     = int(port)
		self.maxpeers = int(maxpeers)
		self.dataDir  = dataDir if dataDir.endswith('/') else dataDir+'/'

		if not os.path.exists(self.dataDir):
			os.makedirs(self.dataDir)

		self.socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.socket.bind((self.host, self.port))
		self.socket.listen(self.maxpeers)

		self.peers = []
		self._lock = threading.Lock()

		self.files = self.getfilelist()[1]
		self.maxfilesize = maxfilesize
		self.numfiles = len(self.files)

		self._shutdown = False

		self.sent_split_files = {}


	def split_send_file(self,path):
		peers  = self.get_active_peers()
		plen   = len(peers)
		size   = os.path.getsize(path)
		chunk  = int(size/plen)
		cmd    = "{'type':'FILEUP'}"
		cmdlen = len(cmd)

		addMod = size % plen

		x = True
		d = {}
		with open(path,'rb') as f:
			for i in peers:
				c = self.create_client_sock()
				c.connect(i)

				c.send(struct.pack('!L',cmdlen))
				c.send(struct.pack('!{}s'.format(cmdlen), cmd.encode()))
				if x:
					b=xor(f.read(chunk+addMod))
					d[hash(b)]=i
					c.send(struct.pack('!L', chunk+addMod))
					c.send(b)
					c.close()
					x = False
				else:
					b=xor(f.read(chunk+addMod))
					d[hash(b)]=i				
					c.send(struct.pack('!L', chunk))
					c.send(b)
					c.close()
		self.sent_split_files[file_hash(path)] = d


	def create_client_sock(self):
		clientsock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
		clientsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		return clientsock


	def get_active_peers(self):
		query = "{'type':'PING'}"
		l = len(query)
		tmp = []
		for i in self.peers:
			d=self.sendtopeer(i,query)
			if struct.unpack('!4s',d)[0].decode() == 'PONG':
				tmp.append(i)
		return tmp


	def getfilelist(self):
		f = os.listdir(self.dataDir)
		d = {}
		for i in f:
			d[file_hash(self.dataDir+i)] = i
		return len(str(d)),d


	def recv_split_file(self,h,path):
		peers = self.sent_split_files[h]
		with open(path,'wb') as f:	
			for i in peers:
				f.write(xor(self.dl_file(peers[i],i,save=False)))


	def sendtopeer(self,peer,msg,wait=True):
		m = struct.pack('!L',len(msg))
		data = struct.pack('!{}s'.format(len(msg)),msg.encode())
		c = self.create_client_sock()
		c.connect(peer)
		c.send(m)
		c.send(data)
		if wait:
			d=struct.unpack('!L',c.recv(4))[0]
			data = c.recv(d)
			c.close()
			return data
		c.close()


	def _sendlen(self,c,m):
		c.send(struct.pack('!L',len(m)))


	def randstr(self):
		return str(uuid.uuid4()).split('-')[0]

	def _peermsg(self,d,c):
		mtype = d['type']
		if mtype == 'PING':
			self._sendlen(c,'PONG')
			c.send(struct.pack('!4s','PONG'.encode()))
			c.close()

		elif mtype == 'PEERLIST':
			m = str(self.peers)
			self._sendlen(c,m)
			l = len(m)
			c.send(struct.pack('!{}s'.format(l),m.encode()))
			c.close()

		elif mtype == 'FILEUP':
			size = struct.unpack('!L',c.recv(4))[0]
			with open(self.dataDir+self.randstr(),'wb') as f:
				f.write(c.recv(size))
			c.close()

		elif mtype == 'FILES':
			l,m = self.getfilelist()
			self._sendlen(c,str(m))
			c.send(struct.pack('!{}s'.format(l),str(m).encode()))
			c.close()

		elif mtype == 'GET':
			fname = d['hash']
			self.files=self.getfilelist()[1]
			if fname in self.files:
				path = self.dataDir+self.files[fname]
				size = os.path.getsize(path)
				c.send(struct.pack('!L',size))
				with open(path,'rb') as f:
					b = f.read(size)
					c.send(b)
				c.close()
			else:
				self._sendlen(c,'NOTFOUND')
				c.send(struct.pack('!{}s'.format(len('NOTFOUND')), 'NOTFOUND'.encode()))
				c.close()

		else:
			c.close()


	def _handle(self, conn):
		msglen = struct.unpack('!L',conn.recv(4))[0]
		if not msglen: return -1
		msg  = conn.recv(msglen)
		data = struct.unpack('!{}s'.format(msglen),msg)[0].decode()
		self._peermsg(ast.literal_eval(data),conn)


	def mainloop(self):
		try:
			while not self._shutdown:
				conn, addr = self.socket.accept()
				print('[*] New connection from ' + str(addr))
				#self.peers.append(conn.getpeername())
				t = threading.Thread(target=self._handle, args=(conn,))
				t.start()
		except KeyboardInterrupt:
			self.socket.close()
			sys.exit(1)


	def updatePeers(self,n):
		self._lock.acquire()
		for i in n:
			if i not in self.peers:
				self.peers.append(i)
		self._lock.release()


	def request_file(self,filehash,name):
		self.files = self.getfilelist()
		if filehash in self.files:
			return

		req = str({'type': 'GET', 'hash':filehash})

		m = struct.pack('!L',len(req))
		data = struct.pack('!{}s'.format(len(req)),req)
		l = len('NOTFOUND')

		for i in self.peers:
			c = self.create_client_sock()
			c.connect(i)
			c.send(m)
			c.send(data)

			d=struct.unpack('!L',c.recv(4))[0]
			if d == l:
				c.close()
				continue
			self.dl_file(i,filehash,name=name)
			break


	def dl_file(self,peer,filehash,name='',save=True):
		req = str({'type': 'GET', 'hash':filehash})

		m = struct.pack('!L',len(req))
		data = struct.pack('!{}s'.format(len(req)),req.encode())
		c = self.create_client_sock()
		c.connect(peer)
		c.send(m)
		c.send(data)
		
		d=struct.unpack('!L',c.recv(4))[0]
		if save:
			with open(self.dataDir+name,'wb') as f:
				f.write(c.recv(d))
				c.close()
		else:
			return c.recv(d)
			c.close()


	def shutdown(self):
		self._shutdown = True


	def run(self):
		self.mainloop()



if __name__ == '__main__':
	try:
		p = Peer('127.0.0.1',6000)
		p.daemon = True
		p.start()
		p.peers=[('127.0.0.1',7000),('127.0.0.1',8000)]
		
		k=input('(blockr) ')
		while k != 'quit':
			if k.startswith('upload'):
				p.split_send_file(k.split(' ')[1])
			elif k.startswith('retrieve'):
				m = k.split(' ')
				p.recv_split_file(m[1],m[2])
			k = input('(blockr) ')
		sys.exit()

		while True: time.sleep(100)

	except KeyboardInterrupt:
		print('Exiting...')
		sys.exit(1)

