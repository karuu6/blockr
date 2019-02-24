from hashlib import sha256
from datetime import datetime

_ts = lambda: datetime.now().__str__()

def hash(d):
	h = sha256()
	h.update(d)
	return h.hexdigest()

def file_hash(fname):
	with open(fname,'rb') as f:
		h = sha256()
		for chunk in iter(lambda: f.read(4096),b''):
			h.update(chunk)
	return h.hexdigest()


# crappy encryption for 
# proof of concept
def xor(d):
	b=bytearray(d)
	for i in range(len(b)):
		b[i] ^= 0x69
	return bytes(b)