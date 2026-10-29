"""Non-spending Builder notices and account-owned tutorial recovery."""
import time
from coc_bot.accounts.store import read,write


def recover(r,frame):
    path=r.config.data_dir/'builder_base/defense_tutorial.json'
    state=read(path,{})
    if state and state.get('account')!=r.config.account_tag:raise ValueError('Builder defense tutorial belongs to another account')
    if r.reader.battle(frame) or r.reader.result_button(frame):return False
    reward=r.reader.daily_reward_close(frame)
    if reward:
        if r.reader.daily_reward_close(r.frame())!=reward:return False
        claim=r.reader.daily_reward_claim(frame)
        if claim:
            if r.reader.daily_reward_claim(r.frame())!=claim:return False
            # The native calendar can require its free reward before Close.
            # Keep a bounded intent across crashes; no unknown follow-up dialog
            # (including converting full inventory) is authorized here.
            day=time.strftime('%Y-%m-%d',time.gmtime())
            record=r.record.setdefault('daily_reward',{'day':day,'attempts':0})
            if record.get('day')!=day:record.update(day=day,attempts=0)
            if record.get('attempts',0)>=2:raise ValueError('Daily reward claim did not finish; calendar needs inspection')
            record['attempts']=record.get('attempts',0)+1;r.phase(r.record['phase'])
            r.tap(claim)
        else:r.tap(reward)
        r.wait(.7);return True
    def first(image):
        if r.reader.find(image,'first_defense_caption',(.23,.49,.51,.65),threshold=.97):
            return r.reader.find(image,'first_defense_cart',(.46,.40,.54,.51),threshold=.97)
        return None
    point=first(frame)
    if point is None and state.get('phase')=='opening_cart' and state.get('cart_taps')==1:
        point=r.reader.find(frame,'first_defense_cart',(.46,.40,.54,.51),threshold=.94)
    if isinstance(point,tuple) and len(point)==2:
        fresh=r.frame()
        again=first(fresh)
        if again is None and state.get('phase')=='opening_cart' and state.get('cart_taps')==1:
            again=r.reader.find(fresh,'first_defense_cart',(.46,.40,.54,.51),threshold=.94)
        if again!=point:return False
        if state.get('cart_taps',0)>=2:raise ValueError('First-defense cart did not open; tutorial paused')
        state.update(account=r.config.account_tag,phase='opening_cart',cart_taps=state.get('cart_taps',0)+1,at=time.time())
        write(path,state);r.check();r.tap(point);r.wait(.7);return True
    if not state or state.get('phase')=='complete':return False
    from coc_bot.builder_base.onboarding import BuilderOnboarding
    speech=BuilderOnboarding(r).speech(frame)
    if speech:
        if BuilderOnboarding(r).speech(r.frame())!=speech:return False
        attempts=state.setdefault('captions',{});key,point=speech
        if attempts.get(key,0)>=2:raise ValueError('First-defense instructions require a new verified target')
        attempts[key]=attempts.get(key,0)+1;write(path,state)
        r.tap(point);r.wait(.7);return True
    from coc_bot.builder_base.resources import ResourceReader
    collector=ResourceReader(r.reader)
    if collector.cart(frame):
        # Normal cart collection is resource income. Its strict title/button
        # checks never authorize an upgrade, potion or gem payment.
        button=collector.cart_collect(frame)
        if button and collector.cart_collect(r.frame())==button:
            if state.get('collect_taps',0)>=1:return False
            state.update(collect_taps=1,phase='collecting');write(path,state)
            r.tap(button);r.wait(1);return True
    if r.reader.home(frame) and not speech:
        if r.reader.home(r.frame()):state.update(phase='complete',completed_at=time.time());write(path,state)
    return False
