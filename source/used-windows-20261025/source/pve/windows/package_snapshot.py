import io,json,pathlib,zipfile,argparse

class Parts(io.RawIOBase):
 def __init__(self,output):
  self.output=output;self.pos=0;self.part=None;self.part_size=0;self.records=[]
 def writable(self):return True
 def seekable(self):return False
 def tell(self):return self.pos
 def write(self,data):
  original=len(data)
  while data:
   if self.part is None:
    name=f'OpenDeploy-Windows-Snapshot.zip.chunk{len(self.records):03d}'
    self.part=(self.output/name).open('xb');self.part_size=0
   count=min(len(data),48*1024*1024-self.part_size)
   chunk=data[:count];self.part.write(chunk);self.part_size+=count;self.pos+=count;data=data[count:]
   if self.part_size==48*1024*1024:self.end_part()
  return original
 def end_part(self):
  if self.part:
   self.part.close();self.records.append({'name':pathlib.Path(self.part.name).name,'bytes':self.part_size});print('sealed',self.records[-1]['name'],flush=True);self.part=None
 def flush(self):
  if self.part:self.part.flush()

def main():
 ap=argparse.ArgumentParser();ap.add_argument('root',type=pathlib.Path);ap.add_argument('output',type=pathlib.Path);args=ap.parse_args()
 root=args.root.resolve();out=args.output;out.mkdir(parents=True,exist_ok=False)
 inventory=json.loads((root/'snapshot-manifest.json').read_text());writer=Parts(out)
 with zipfile.ZipFile(writer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
  for name in inventory['directories']:z.writestr(name+'/',b'')
  for item in inventory['files']+[{'path':'snapshot-manifest.json'}]:
   p=root/item['path'];stored=p.suffix.lower() in ['.iso','.zip','.gz','.zst','.xz','.png'] or '.part' in p.name
   z.write(p,item['path'],compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
 writer.end_part()
 release={'schema':1,'source_commit':(root/'SOURCE-COMMIT.txt').read_text().strip(),'archive_bytes':writer.pos,'parts':writer.records}
 (out/'snapshot-release.json').write_text(json.dumps(release,indent=2)+'\n')
 print(json.dumps(release),flush=True)
if __name__=='__main__':main()
