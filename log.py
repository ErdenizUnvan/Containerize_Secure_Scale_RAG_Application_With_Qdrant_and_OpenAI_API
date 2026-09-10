import os
pwd=os.getcwd()
loglar=[]
for x in os.listdir(pwd):
    if x.startswith('log') and os.path.isdir(x):
        loglar.append(os.path.join(x,'app.log'))
print(f'loglar:{loglar}')
out = open('total.log','w')
for file in loglar:
    number=file.find('/')
    container = file[4:number]
    f = open(file,'r') #read
    for line in f:
        out.write(f'container no: '+ container+' '+line+'\n')
    f.close()
out.close()
