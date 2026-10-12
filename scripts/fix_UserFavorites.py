#!/usr/bin/env python3
"""Fix [5]: make UserFavoritesPresenter.v0() main-thread safe (classes8.dex).

Symptom (reproduced 3x on the Redmi phone, see docs/findings.md section 12):

    FATAL EXCEPTION: main
    java.lang.RuntimeException: HMI callback exception:ThreadId(...):
      android.view.ViewRootImpl$CalledFromWrongThreadException:
      Only the original thread that created a view hierarchy can touch its views.
      Expected: main  Calling: bl_thd_pool_wor
        android.view.View.requestLayout
        android.widget.TextView.setText
        k.e.j.d.j0.updateViewText
        k.e.v.j.f.f.h2
        com.autosdk.user.presenter.behavior.UserFavoritesPresenter.v0
        ...UserFavoritesPresenter$3.notify
        com.autosdk.bussiness.user.model.SyncSdkModel.notify
        com.autonavi.gbl.user.router.SyncSDKServiceObserverRouter.notify
        ...SyncsdkObserverJNI.SwigDirector_ISyncSDKServiceObserverImpl_notify

The sync-SDK observer callback is delivered by the native GBL thread pool
("bl_thd_pool_worker" - the string only exists in lib/arm64-v8a/libGComm3rd.so).
The whole notify() chain runs on that worker thread.  Every other call in the
chain is already thread-safe:

    d2()/j2()  -> TaskManager.post(...)                (already dispatches)
    X0()->W0() -> SharedPreferences write              (thread-safe)
    t0()/s0()/u0() -> RxJava .observeOn(mainThread)    (already dispatches)
    v0()       -> k.e.v.j.f.f.h2() -> updateViewText() -> TextView.setText()
                  *** the only direct View touch, and it is NOT guarded ***

This is a pre-existing bug in the BYD/Amap integration layer, not something
introduced by our patches (the unmodified original classes8.dex behaves
identically - see docs/findings.md).

Fix: insert a main-looper guard at the very top of v0().  When v0() is called
from a non-main thread, re-dispatch to the main thread through
TaskManager.post(...) - the same helper d2()/j2() already use - and return.
TaskManager.post() runs the Runnable inline when it is already on the main
looper thread, so main-thread callers keep the exact current behaviour and we
only add one extra Runnable allocation for them.

The new Runnable is Lk/e/v/h/c/m; (that package already holds a..l, so m is
free, and the dex contains no such class).

NOTE on the branch: `if-eq v0, v1, :cond_v0_main` jumps to the original body
when myLooper() == getMainLooper() (i.e. already on main).  Off-main (including
myLooper()==null on a native thread) falls through to the post + return.  Using
`if-ne` here would be inverted and, because TaskManager.post() runs inline on
main, would recurse forever on the main-thread call path (StackOverflowError).

Runs inside the baksmali output directory of classes8.dex.
"""
import os

TARGET = 'smali_out/smali/com/autosdk/user/presenter/behavior/UserFavoritesPresenter.smali'
NEW_CLASS = 'smali_out/smali/k/e/v/h/c/m.smali'

OLD = """.method public v0()V
    .locals 7
"""

NEW = """.method public v0()V
    .locals 9

    invoke-static {}, Landroid/os/Looper;->myLooper()Landroid/os/Looper;

    move-result-object v0

    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;

    move-result-object v1

    if-eq v0, v1, :cond_v0_main

    new-instance v0, Lk/e/v/h/c/m;

    invoke-direct {v0, p0}, Lk/e/v/h/c/m;-><init>(Lcom/autosdk/user/presenter/behavior/UserFavoritesPresenter;)V

    invoke-static {v0}, Lcom/autosdk/bussiness/common/task/TaskManager;->post(Ljava/lang/Runnable;)V

    return-void

    :cond_v0_main
"""

RUNNABLE = """.class public final Lk/e/v/h/c/m;
.super Ljava/lang/Object;
.source "SourceFile"

# interfaces
.implements Ljava/lang/Runnable;


# instance fields
.field public final synthetic c:Lcom/autosdk/user/presenter/behavior/UserFavoritesPresenter;


# direct methods
.method public synthetic constructor <init>(Lcom/autosdk/user/presenter/behavior/UserFavoritesPresenter;)V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    iput-object p1, p0, Lk/e/v/h/c/m;->c:Lcom/autosdk/user/presenter/behavior/UserFavoritesPresenter;

    return-void
.end method


# virtual methods
.method public final run()V
    .locals 1

    iget-object v0, p0, Lk/e/v/h/c/m;->c:Lcom/autosdk/user/presenter/behavior/UserFavoritesPresenter;

    invoke-virtual {v0}, Lcom/autosdk/user/presenter/behavior/UserFavoritesPresenter;->v0()V

    return-void
.end method
"""


def main():
    assert os.path.isfile(TARGET), f"missing {TARGET}"
    assert not os.path.exists(NEW_CLASS), f"{NEW_CLASS} already exists"
    assert ':cond_v0_main' not in open(TARGET, encoding='utf-8').read(), "already patched"

    s = open(TARGET, encoding='utf-8').read()
    n = s.count(OLD)
    assert n == 1, f"v0() anchor count = {n} (expected 1)"

    open(TARGET, 'w', encoding='utf-8').write(s.replace(OLD, NEW, 1))
    with open(NEW_CLASS, 'w', encoding='utf-8') as f:
        f.write(RUNNABLE)

    print("    patched UserFavoritesPresenter.v0() -> main-looper guard")
    print("    added   k/e/v/h/c/m.smali (Runnable -> v0())")


if __name__ == '__main__':
    main()
