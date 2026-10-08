#!/usr/bin/env python3
import os,subprocess,tempfile
root=os.path.dirname(os.path.dirname(__file__)); audit=os.path.join(root,'build','kernel_audit.py')
def src(a,b,extra=''):
 return '''struct x mhi_foxconn_dw5934e_info = { .config = &modem_foxconn_sdx72_config, };
static const struct pci_device_id mhi_pci_id_table[] = {
{ PCI_DEVICE(0x105b, 0xe11d), .driver_data = (kernel_ulong_t) &%s },
{ PCI_DEVICE(0x105b, 0xe11e), .driver_data = (kernel_ulong_t) &%s },%s
};'''%(a,b,extra)
with tempfile.TemporaryDirectory() as d:
 def run(text):
  p=os.path.join(d,'x.c');open(p,'w').write(text);return subprocess.run(['python',audit,p]).returncode
 assert run(src('mhi_foxconn_dw5934e_info','mhi_foxconn_dw5934e_info'))==0
 assert run(src('wrong','mhi_foxconn_dw5934e_info'))!=0
 assert run(src('mhi_foxconn_dw5934e_info','wrong'))!=0
 assert run(src('wrong','wrong','\n{ PCI_DEVICE(0x9999, 0x0001), .driver_data = (kernel_ulong_t) &mhi_foxconn_dw5934e_info },'))!=0
 assert run('/* '+src('mhi_foxconn_dw5934e_info','mhi_foxconn_dw5934e_info')+' */\n'+src('wrong','wrong'))!=0
print('PASS: kernel audit rejects cross-entry, wrong and comment-fake mappings')
