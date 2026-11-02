package controllers.battle.qc2.maplogic
{
   import com.bit101.components.HBox;
   import com.game.engine.core.GameFrame;
   import com.game.engine.utils.SimpleTextLog;
   import com.game.net.AssetItem;
   import com.game.net.AssetManager;
   import com.game.net.AssetsURL;
   import com.ywxgame.models.manager.EventManager;
   import controllers.battle.qc2.BattleLogic;
   import controllers.battle.qc2.SimulateServerFrame;
   import controllers.battle.qc2.GameOverLogic;
   import controllers.battle.qc2.PlayPvpVideoCmd;
   import controllers.battle.qc2.gameovers.GameOverZhuXie;
   import controllers.battle.zhuxie.ZhuXieBattleHander;
   import flash.display.DisplayObject;
   import flash.display.MovieClip;
   import flash.display.Sprite;
   import flash.events.Event;
   import models.constants.Const;
   import models.managers.BuffModelManager;
   import models.proxys.ZhuXieProxy;
   import models.vo.RoleConfigVO;
   import models.vo.UserVO;
   import modules.ApplicationFacade;
   import modules.zhuXie.model.ZhuXProxy;
   import viewers.container.BattleMap;
   import viewers.entitys.Entity;
   import viewers.entitys.man.PlayerEntity;
   import viewers.entitys.man.RoleEntity;
   import viewers.entitys.others.BattleExitGateway;
   
   public class MapZhuXie extends MapLogicBase
   {
       
      
      private var hbox:HBox;
      
      private var _timeTip:MovieClip;
      
      private var _hasEnter:Boolean;
      
      private var _diff:Array;
      
      private var _hasBuffs:Object;
      
      private var _manEntitys:Array;
      
      public function MapZhuXie(param1:BattleLogic)
      {
         _manEntitys = [];
         super(param1);
         EventManager.on("evt_zhuXie_endZhuXieChallenge",this.evt_zhuXie_endZhuXieChallenge);
         EventManager.on("evt_zhuXie_endZhuXieChallengeFail",this.evt_zhuXie_endZhuXieChallengeFail);
         EventManager.on("onOnePlayerFinish",this.onOnePlayerFinish);
      }
      
      private function onOnePlayerFinish(param1:Object) : void
      {
         SimpleTextLog.getIns().log2("onOnePlayerFinish",JSON.stringify(param1));
         ZhuXProxy.setScore({"zhuXie":{
            "score":param1.message.totalScore,
            "cur":8
         }});
         param1.message.charID = battleLogic.users[0].charID;
         showGameOver(param1.message.result == 1,param1.message);
      }
      
      override public function advanceTime(param1:Number) : void
      {
         super.advanceTime(param1);
         this.updateTimeView((battleLogic.levelParame.config.countDownTime - battleLogic.getTimer()) / 1000);
      }
      
      override public function initMonsterConfig(param1:RoleConfigVO) : void
      {
         var _loc3_:int = battleLogic.levelParame.config.id;
         var _loc2_:Object = ZhuXieProxy.GetConfigByDungeonID_MId(param1.id,_loc3_);
         SimpleTextLog.getIns().log2("initMonsterConfig",param1.id);
         if(_loc2_)
         {
            for(var _loc4_ in _loc2_)
            {
               if(_loc4_ != "id")
               {
                  try
                  {
                     param1[_loc4_] = _loc2_[_loc4_];
                  }
                  catch(error:Error)
                  {
                     trace("error",error);
                  }
               }
            }
         }
      }
      
      override public function onPlayerDeadCmd(param1:Entity) : void
      {
         super.onPlayerDeadCmd(param1);
      }
      
      override public function onAllPlayerDeadCmd() : void
      {
         super.onAllPlayerDeadCmd();
         this.enterGateWay(0,"onAllPlayerDeadCmd");
      }
      
      override public function enterGateWay(param1:int, param2:Object) : void
      {
         if(battleLogic.levelParame.isVideo)
         {
            battleLogic.playVideoComplete();
            return;
         }
         if(_hasEnter)
         {
            return;
         }
         battleLogic.pause();
         _hasEnter = true;
         if(param1 == 0)
         {
            ZhuXieBattleHander.getIns().exit(false,param2);
         }
         else if(param1 == 1)
         {
            ZhuXieBattleHander.getIns().next();
         }
         ApplicationFacade.getInstance().sendNotification(Const.NF_REMOVE_HIT);
      }
      
      override public function createBattleUI() : void
      {
         super.createBattleUI();
         var _loc5_:String = AssetsURL.getMapURL(battleLogic.levelParame.config.mapURL + ".swf");
         var _loc4_:AssetItem;
         var _loc3_:Class = (_loc4_ = AssetManager.getIns().getAsset(_loc5_)).loaderInfo.applicationDomain.getDefinition("btn_back") as Class;
         hbox = new HBox(_ui);
         var _loc2_:DisplayObject = new _loc3_();
         hbox.addChild(_loc2_);
         hbox.draw();
         hbox.y = 590 - hbox.height / 2;
         hbox.x = 470;
         _loc2_.addEventListener("click",this.onBtnBackClick);
         var _loc1_:Class = _loc4_.loaderInfo.applicationDomain.getDefinition("time_tip") as Class;
         if(_loc1_)
         {
            _timeTip = new _loc1_();
            this._ui.addChild(_timeTip as Sprite);
            _timeTip.x = 470;
            _timeTip.y = 0;
            this.updateTimeView(battleLogic.levelParame.config.countDownTime / 1000);
         }
      }
      
      override public function goEndtScreen() : void
      {
         var _loc3_:int = 0;
         var _loc1_:RoleEntity = null;
         var _loc2_:BattleExitGateway = null;
         super.goEndtScreen();
         ApplicationFacade.getInstance().sendNotification(Const.NF_REMOVE_HIT);
         if(battleLogic.isAutoEnterGateway)
         {
            _loc3_ = 0;
            while(_loc3_ < this._manEntitys.length)
            {
               _loc1_ = this._manEntitys[_loc3_];
               if(_loc1_ && !_loc1_.isDie)
               {
                  _loc1_.canuseKey = false;
               }
               _loc3_++;
            }
            _loc2_ = BattleMap.Ins.map.getExitBattleGateway1();
            if(_loc2_)
            {
               _loc2_.destory();
            }
         }
      }
      
      override public function clearSlowEff() : void
      {
         super.clearSlowEff();
         if(battleLogic.levelParame.isVideo)
         {
            battleLogic.playVideoComplete();
            return;
         }
         if(battleLogic.isAutoEnterGateway)
         {
            this.enterGateWay(0,"slow");
         }
      }
      
      override public function fail() : void
      {
         super.fail();
         this.onAllPlayerDeadCmd();
      }
      
      private function updateTimeView(param1:int) : void
      {
         var _loc3_:int = 0;
         var _loc4_:int = 0;
         var _loc2_:Array = String(param1).split("");
         _loc2_ = _loc2_.reverse();
         _loc3_ = 0;
         while(_loc3_ < 3)
         {
            _timeTip.mc_dis["m" + (_loc3_ + 1)].gotoAndStop(1);
            _loc3_++;
         }
         _loc4_ = 0;
         while(_loc4_ < _loc2_.length)
         {
            _timeTip.mc_dis["m" + (_loc4_ + 1)].gotoAndStop(int(_loc2_[_loc4_]) + 1);
            _loc4_++;
         }
      }
      
      protected function onBtnBackClick(param1:Event) : void
      {
         battleLogic.pause();
         if(battleLogic.levelParame.isVideo)
         {
            battleLogic.playVideoComplete();
         }
         else
         {
            this.enterGateWay(0,"back");
            if(GameFrame.current)
            {
               GameFrame.current.remove();
            }
         }
      }
      
      private function evt_zhuXie_endZhuXieChallenge(param1:Object) : void
      {
         if(!param1.zhuXie.time)
         {
            param1.zhuXie.time = battleLogic.getTimer() / 1000;
         }
         param1.zhuXie.score = param1.score;
         this.showGameOver(param1.win,param1.zhuXie);
      }
      
      private function evt_zhuXie_endZhuXieChallengeFail(param1:Object) : void
      {
         this.showGameOver(false,{});
      }
      
      private function showGameOver(param1:Boolean, param2:Object) : void
      {
         if(_gameOverUI)
         {
            return;
         }
         SimpleTextLog.getIns().log2("showGameOver" + param1);
         if(!param2.charID)
         {
            param2.charID = battleLogic.users[0].charID;
         }
         var _loc3_:GameOverLogic = new GameOverZhuXie();
         param2.result = param1 ? 1 : 0;
         _loc3_.setInit(this.battleLogic.levelParame,param2);
         _loc3_.createView();
         _gameOverUI = _loc3_;
         ApplicationFacade.getInstance().sendNotification(Const.NF_REMOVE_HIT);
      }
      
      override public function playVideoComplete(param1:Object) : void
      {
         SimulateServerFrame.prepareReplayResult(param1);
         var _loc2_:int = 0;
         super.playVideoComplete(param1);
         var _loc3_:* = param1.playerResult[0].result == 5;
         _loc2_ = PlayPvpVideoCmd.lastFrame / 30;
         battleLogic.pause();
         if(SimulateServerFrame.researchAfterComplete(param1)) return;
         if(SimulateServerFrame.seedBankAfterComplete(param1)) return;
         this.showGameOver(_loc3_,{
            "win":_loc3_,
            "time":_loc2_,
            "charID":battleLogic.users[0].charID,
            "addTimes":param1.sceneInfo.addTimes,
            "score":param1.sceneInfo.score
         });
      }
      
      override public function canChange(param1:PlayerEntity) : Boolean
      {
         var _loc5_:int = 0;
         var _loc2_:int = 0;
         var _loc4_:Object = null;
         var _loc3_:Object = null;
         checkDiff(param1.userVo.userId);
         _loc5_ = 0;
         while(_loc5_ < this._diff.length)
         {
            _loc2_ = int(this._diff[_loc5_]);
            _loc4_ = ZhuXieProxy.GetZhuXieWordById(_loc2_);
            _loc3_ = JSON.parse(_loc4_.param);
            if(_loc4_ && _loc3_.isCanChangeProfession == false)
            {
               return false;
            }
            _loc5_++;
         }
         return super.canChange(param1);
      }
      
      private function checkDiff(param1:Number) : void
      {
         var _loc2_:Array = null;
         var _loc3_:int = 0;
         if(!_diff)
         {
            if(this.battleLogic.response && this.battleLogic.response.playerInfos)
            {
               _loc2_ = this.battleLogic.response.playerInfos;
               _loc3_ = 0;
               while(_loc3_ < _loc2_.length)
               {
                  if(_loc2_[_loc3_] && _loc2_[_loc3_].playerId == param1)
                  {
                     _diff = _loc2_[_loc3_].diff != null ? _loc2_[_loc3_].diff : new Array();
                     break;
                  }
                  _loc3_++;
               }
            }
            else
            {
               _diff = [];
            }
         }
      }
      
      override protected function getCreateRoleInfoUsers() : Array
      {
         var _loc3_:int = 0;
         var _loc1_:UserVO = null;
         var _loc2_:Array = [];
         _loc3_ = 0;
         while(_loc3_ < battleLogic.users.length)
         {
            _loc1_ = battleLogic.users[_loc3_];
            _loc2_.push(_loc1_);
            _loc3_++;
         }
         return _loc2_;
      }
      
      override public function onAddUservo(param1:UserVO) : void
      {
         var _loc5_:int = 0;
         var _loc2_:int = 0;
         var _loc4_:Object = null;
         var _loc3_:Object = null;
         super.onAddUservo(param1);
         this.checkDiff(param1.userId);
         _loc5_ = 0;
         while(_loc5_ < this._diff.length)
         {
            _loc2_ = int(this._diff[_loc5_]);
            _loc4_ = ZhuXieProxy.GetZhuXieWordById(_loc2_);
            _loc3_ = JSON.parse(_loc4_.param);
            if(_loc4_ && _loc3_.isCanUseMagicWeapon == false)
            {
               param1.keyBoard.setKey(72,-1);
               param1.keyBoard.setKey(103,-1);
               if(param1.keyBoard2)
               {
                  param1.keyBoard2.setKey(72,-1);
                  param1.keyBoard2.setKey(103,-1);
               }
               if(param1.children)
               {
                  param1.children.keyBoard.setKey(72,-1);
                  param1.children.keyBoard.setKey(103,-1);
                  if(param1.children.keyBoard2)
                  {
                     param1.children.keyBoard2.setKey(72,-1);
                     param1.children.keyBoard2.setKey(103,-1);
                  }
               }
            }
            _loc5_++;
         }
         param1.doubleProtectPoint = 0;
      }
      
      override public function onAddMUservo(param1:UserVO) : void
      {
         super.onAddMUservo(param1);
         param1.doubleProtectPoint = 0;
      }
      
      override public function addEntity(param1:RoleEntity) : void
      {
         var _loc9_:int = 0;
         var _loc3_:int = 0;
         var _loc7_:Object = null;
         var _loc4_:Object = null;
         var _loc5_:UserVO = null;
         var _loc2_:UserVO = null;
         var _loc8_:int = 0;
         var _loc6_:Array = null;
         super.addEntity(param1);
         if(!_hasBuffs)
         {
            _hasBuffs = {};
         }
         _manEntitys.push(param1);
         _loc9_ = 0;
         while(_loc9_ < this._diff.length)
         {
            _loc3_ = int(this._diff[_loc9_]);
            _loc7_ = ZhuXieProxy.GetZhuXieWordById(_loc3_);
            _loc4_ = JSON.parse(_loc7_.param);
            if(_loc7_.type == 1)
            {
               _loc8_ = 0;
               while(_loc8_ < battleLogic.users.length)
               {
                  if((_loc5_ = battleLogic.users[_loc8_]).entitieId == param1.userVo.entitieId && !_hasBuffs[_loc7_.id])
                  {
                     if(_loc7_ && _loc4_.myBuffIds)
                     {
                        BuffModelManager.getIns().createBuff(_loc4_.myBuffIds,null,1,_loc5_,_loc5_);
                        if(_loc4_.myBuff1Times == 1)
                        {
                           _hasBuffs[_loc7_.id] = true;
                        }
                     }
                  }
                  _loc8_++;
               }
            }
            else if(_loc7_.type == 2)
            {
               _loc8_ = 0;
               while(_loc8_ < battleLogic.musers.length)
               {
                  _loc2_ = battleLogic.musers[_loc8_];
                  _loc6_ = battleLogic.levelParame.config.monsterID != null ? battleLogic.levelParame.config.monsterID : new Array();
                  if(_loc2_.entitieId == param1.userVo.entitieId && _loc6_.indexOf(_loc2_.configVo.id + "") > -1)
                  {
                     if(_loc7_ && _loc4_.myBuffIds)
                     {
                        BuffModelManager.getIns().createBuff(_loc4_.myBuffIds,null,1,_loc2_,_loc2_);
                     }
                  }
                  _loc8_++;
               }
            }
            _loc9_++;
         }
      }
      
      override public function destroy() : void
      {
         super.destroy();
         if(hbox)
         {
            hbox.removeChildren();
            if(hbox.parent && hbox.parent.contains(hbox))
            {
               hbox.parent.removeChild(hbox);
            }
         }
         hbox = null;
         EventManager.off("evt_zhuXie_endZhuXieChallenge",this.evt_zhuXie_endZhuXieChallenge);
         EventManager.off("evt_zhuXie_endZhuXieChallengeFail",this.evt_zhuXie_endZhuXieChallengeFail);
         EventManager.off("onOnePlayerFinish",this.onOnePlayerFinish);
      }
   }
}
