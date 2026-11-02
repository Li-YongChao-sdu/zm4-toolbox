package controllers.battle.qc2.gameovers
{
   import com.game.engine.utils.SimpleTextLog;
   import controllers.battle.qc2.GameOverLogic;
   import controllers.battle.qc2.SimulateServerFrame;
   import models.managers.BattleModelManager;
   import flash.utils.Timer;
   import flash.events.TimerEvent;
   import flash.events.MouseEvent;
   import controllers.battle.zhuxie.ZhuXieBattleHander;
   import flash.display.MovieClip;
   import flash.text.TextField;
   import models.constants.Const;
   import models.managers.DateModelManager;
   import models.managers.ManModelManager;
   import models.vo.module.GameOverVo;
   import models.vo.module.ItemVoManager;
   import modules.ApplicationFacade;
   import modules.utils.CreateComponent;
   
   public class GameOverZhuXie extends GameOverLogic
   {
       
      
      private var retryTimer:Timer;

      private var timeTxt:TextField;
      
      private var statusTxt:TextField;
      
      private var bestTxt:TextField;
      
      public function GameOverZhuXie()
      {
         super();
      }
      
      override protected function show(param1:MovieClip) : void
      {
         super.show(param1);
         if(this.data.result == 1)
         {
            if(param1["btn_cxtz"])
            {
               param1["btn_cxtz"].visible = false;
            }
            timeTxt = CreateComponent.createTextField(42,7,211,33,"left",26);
            statusTxt = CreateComponent.createTextField(42,7,211,33,"left",26);
            bestTxt = CreateComponent.createTextField(42,7,211,33,"left",26);
            param1.mc_ggys.mc.addChild(timeTxt);
            param1.mc_ggzt.mc.addChild(statusTxt);
            param1.mc_zglj.mc.addChild(bestTxt);
            timeTxt.text = "通关时间 " + DateModelManager.getIns().getTimeFormatByNum(data.time,":",2);
            statusTxt.text = "当前倍率 " + (data.addTimes || true);
            bestTxt.text = "净化魔气值 " + data.score + "";
            this.calcTotalScore(this.data.score);
         }
         param1.mc_role.mc.gotoAndStop(ManModelManager.getIns().getRoleIconFrame(data.charID));
         SimulateServerFrame.liveDialogSeen({result:this.data.result,charID:data.charID,isVideo:this.levelParam.isVideo,
            levelId:BattleModelManager.getIns().levelInfo != null ? BattleModelManager.getIns().levelInfo.id : 0});
         if(!this.levelParam.isVideo && !this.levelParam.isMultiplayer && BattleModelManager.getIns().levelInfo != null && BattleModelManager.getIns().levelInfo.id == 300109)
         {
            SimulateServerFrame.liveResultArrived(this.data.result == 1);
            if(this.data.result == 0)
            {
               retryTimer = new Timer(1200);
               retryTimer.addEventListener(TimerEvent.TIMER,onAutoRetry);
               retryTimer.start();
            }
         }
      }
      
      private function onAutoRetry(e:TimerEvent) : void
      {
         if(this._mc == null || this._mc.stage == null)
         {
            stopRetryTimer();
            return;
         }
         if(!SimulateServerFrame.liveAutoRetryAllowed || this.data.result != 0) return;
         if(!this._mc["btn_cxtz"] || !this._mc["btn_cxtz"].visible || !this._mc["btn_cxtz"].mouseEnabled) return;
         stopRetryTimer();
         SimulateServerFrame.liveRetryClicked();
         this._mc["btn_cxtz"].dispatchEvent(new MouseEvent(MouseEvent.CLICK,true));
      }

      private function stopRetryTimer() : void
      {
         if(retryTimer != null)
         {
            retryTimer.stop();
            retryTimer.removeEventListener(TimerEvent.TIMER,onAutoRetry);
            retryTimer = null;
         }
      }

      override public function destroy() : void
      {
         stopRetryTimer();
         super.destroy();
      }

      override protected function getToGoTownParam() : Object
      {
         return {"openModule":"zhuXie"};
      }
      
      private function calcTotalScore(param1:int) : void
      {
         var _loc7_:int = 0;
         var _loc6_:GameOverVo = null;
         var _loc5_:Array = null;
         var _loc2_:Number = NaN;
         var _loc4_:Number = NaN;
         var _loc3_:int = 0;
         _loc7_ = 0;
         while(_loc7_ < ItemVoManager.getIns().gameOverVos.length)
         {
            _loc2_ = Number((_loc5_ = (_loc6_ = ItemVoManager.getIns().gameOverVos[_loc7_]).zhuxieScore.split(";"))[0]);
            _loc4_ = Number(_loc5_[1]);
            if(param1 >= _loc2_ && param1 <= _loc4_)
            {
               _loc3_ = _loc6_.id;
               break;
            }
            _loc7_++;
         }
         this._mc.mc_total.mc.gotoAndStop(_loc3_ + 1);
      }
      
      override protected function onReplay() : void
      {
         stopRetryTimer();
         if(this.levelParam.isVideo)
         {
            SimpleTextLog.getIns().log2("这是回放");
            return;
         }
         ZhuXieBattleHander.getIns().create();
         ApplicationFacade.getInstance().sendNotification(Const.NF_REMOVE_HIT);
      }
   }
}
