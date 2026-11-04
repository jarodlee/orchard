"""Compile the actual transient-input gate and exercise the observed 42/62/42 sequence."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'kernel/patches/drivers/power/0019-power-supply-apple-tristar-reidentify-after-transient-input.patch'


def gate():
    source = '\n'.join(line[1:] for line in PATCH.read_text().splitlines()
                       if line[:1] in (' ', '+') and not line.startswith('+++'))
    start = source.index('static bool tristar_input_ready(')
    opening = source.index('{', start)
    depth = 0
    for end in range(opening, len(source)):
        depth += source[end] == '{'
        depth -= source[end] == '}'
        if not depth:
            return source[start:end + 1]
    raise ValueError('Incomplete driver helper')


class InputRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc') or shutil.which('clang')
        if not cc:
            raise unittest.SkipTest('A C compiler is required')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        path = Path(cls.temp.name)
        program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <limits.h>
typedef uint64_t u64;
#define READ_ONCE(x) (x)
#define TRISTAR_CHG_STATUS_ONLINE 0x42
#define TRISTAR_CHG_FALLBACK_CODE 34
#define TRISTAR_SETTLING 1
#define TRISTAR_RAMPING 2
#define TRISTAR_CHARGING 3
#define TRISTAR_FAULT 4
struct tristar_charger {
    unsigned code, phase, epoch, usb_epoch, usb_ma;
    bool input_unstable, present;
};
static unsigned withdrawals, attachments;
static u64 attach_time;
static void tristar_withdraw(struct tristar_charger *c, unsigned code) {
    if(c->code>code) { c->code=code; withdrawals++; }
}
/* Existing attachment contract: source identification, not a cached ramp. */
static void tristar_new_attachment(struct tristar_charger *c, u64 now) {
    attachments++; attach_time=now; c->input_unstable=false;
    c->present=true; c->phase=TRISTAR_SETTLING;
}
'''
        program += gate()
        program += r'''
int main(int argc, char **argv) {
    struct tristar_charger c={.code=186,.phase=TRISTAR_CHARGING,
        .epoch=7,.usb_epoch=7,.usb_ma=500,.present=true};
    assert(argc==2);
    if(!strcmp(argv[1],"normal")) {
        assert(tristar_input_ready(&c,0x42,100));
        assert(!withdrawals&&!attachments&&c.code==186&&c.usb_epoch==7);
    } else if(!strcmp(argv[1],"observed")) {
        assert(!tristar_input_ready(&c,0x62,100));
        assert(c.code==34&&c.input_unstable&&withdrawals==1&&!attachments);
        assert(!tristar_input_ready(&c,0x42,204));
        assert(attachments==1&&c.phase==TRISTAR_SETTLING&&attach_time==204);
        assert(c.usb_epoch!=c.epoch);
    } else if(!strcmp(argv[1],"repeated")) {
        for(unsigned i=0;i<100;i++) assert(!tristar_input_ready(&c,0x62,i));
        assert(withdrawals==1&&!attachments);
        assert(!tristar_input_ready(&c,0x42,200));
        for(unsigned i=0;i<100;i++) assert(tristar_input_ready(&c,0x42,201+i));
        assert(attachments==1);
    } else if(!strcmp(argv[1],"ramping")) {
        c.phase=TRISTAR_RAMPING;
        assert(!tristar_input_ready(&c,0x40,1));
        assert(!tristar_input_ready(&c,0x42,2));
        assert(attachments==1&&c.phase==TRISTAR_SETTLING);
    } else if(!strcmp(argv[1],"fault")) {
        c.phase=TRISTAR_FAULT;
        assert(!tristar_input_ready(&c,0x62,1));
        assert(tristar_input_ready(&c,0x42,2));
        assert(c.phase==TRISTAR_FAULT&&!attachments&&c.code==34);
    } else if(!strcmp(argv[1],"initial")) {
        c.present=false;
        assert(!tristar_input_ready(&c,0x40,1));
        assert(tristar_input_ready(&c,0x42,2));
        assert(!attachments); /* normal poll handles the first attachment */
    } else if(!strcmp(argv[1],"lower")) {
        c.code=2;
        assert(!tristar_input_ready(&c,0x62,1));
        assert(c.code==2&&!withdrawals&&!attachments);
    } else if(!strcmp(argv[1],"changing")) {
        assert(!tristar_input_ready(&c,0x40,1));
        assert(!tristar_input_ready(&c,0x62,2));
        assert(!attachments);
        assert(!tristar_input_ready(&c,0x42,3));
        assert(attachments==1&&attach_time==3);
    } else if(!strcmp(argv[1],"wrap")) {
        c.epoch=0; c.usb_epoch=0;
        assert(!tristar_input_ready(&c,0x62,1));
        assert(!tristar_input_ready(&c,0x42,2));
        assert(c.usb_epoch==UINT_MAX);
    } else return 2;
    return 0;
}
'''
        source = path / 'recovery.c'
        source.write_text(program)
        cls.binary = path / 'recovery'
        subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(cls.binary)],
                       check=True, capture_output=True)

    def test_actual_driver_gate(self):
        for case in ('normal', 'observed', 'repeated', 'ramping', 'fault', 'initial', 'lower', 'changing', 'wrap'):
            with self.subTest(case=case):
                subprocess.run([str(self.binary), case], check=True, timeout=5)

    def test_gate_is_called_before_existing_fault_and_ramp_logic(self):
        text = PATCH.read_text()
        self.assertIn('+\tif (!tristar_input_ready(chg, status, now))', text)
        self.assertIn('+\tchg->input_unstable = false;', text)
        self.assertNotIn('+\t\tchg->code =', text)
