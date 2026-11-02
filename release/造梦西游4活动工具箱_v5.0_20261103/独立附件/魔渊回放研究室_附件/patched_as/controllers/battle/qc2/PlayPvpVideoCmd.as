package controllers.battle.qc2
{
   import com.game.engine.utils.SimpleTextLog;
   import com.game.net.AssetManager;
   import com.game.net.AssetsURL;
   import models.configs.LevelConfigVO;
   import models.managers.BattleModelManager;
   import models.managers.CGModelManager;
   import models.managers.GlobalData;
   import models.managers.LevelModelManager;
   import models.vo.LevelParam;
   import models.vo.RequestVO;
   import modules.ApplicationFacade;
   import modules.utils.CreateComponent;
   import org.puremvc.as3.interfaces.INotification;
   import org.puremvc.as3.patterns.command.SimpleCommand;
   import viewers.PreloadMediator;
   
   public class PlayPvpVideoCmd extends SimpleCommand
   {
      
      public static var data:Object;
      
      public static var lastFrame:Number;
       
      
      public function PlayPvpVideoCmd()
      {
         super();
      }
      
      override public function execute(param1:INotification) : void
      {
         var _loc3_:String = null;
         var _loc4_:RequestVO = null;
         var _loc5_:String = null;
         var _loc2_:Object = param1.getBody();
         if(_loc2_ != null && _loc2_.localResponse != null)
         {
            onGetRepot(_loc2_.localResponse);
            return;
         }
         if(_loc2_)
         {
         }
         if(_loc2_)
         {
            _loc3_ = SimulateServerFrame.seedBankResolveCode(String(_loc2_.code));
            (_loc4_ = new RequestVO("copyReport.copyReportHandler.getReport",{"reportId":_loc3_})).callBackFunc = onGetRepot;
            _loc4_.loading = true;
            facade.sendNotification("cmdRequestServer",_loc4_);
         }
         else
         {
            _loc5_ = "zhuxie_666.json";
            _loc5_ = AssetsURL.getAssetsUrl(_loc5_);
            AssetManager.getIns().loadAsset(_loc5_,"bytes",onDataLoadComplete);
         }
      }
      
      private function onGetRepot(param1:Object) : void
      {
         var res:Object = param1;
         var error:Boolean = false;
         if(res.code == 200)
         {
            if(res.hasOwnProperty("report"))
            {
               if(res.report.hasOwnProperty("cg") == false)
               {
                  error = true;
               }
            }
         }
         if(res.code == 200)
         {
            ApplicationFacade.getInstance().removeMediator("BattleMapMediator");
            CGModelManager.isUse = res.report.cg != GlobalData.CurrCg;
            SimpleTextLog.getIns().log("onGetRepot cg=",res.report.cg,"GlobalData.CurrCg=" + GlobalData.CurrCg,"isUse=" + CGModelManager.isUse);
            if(CGModelManager.isUse)
            {
               CGModelManager.getIns().loadCg(res.report.cg,function():void
               {
                  play(res);
               });
            }
            else
            {
               this.play(res);
            }
         }
         else
         {
            CreateComponent.createAutoWarnBar("已过期！");
         }
      }
      
      private function play(param1:Object) : void
      {
         var _loc3_:Boolean = false;
         param1.report.battleType = int(param1.report.battleType);
         var _loc2_:int = int(param1.report.copyId);
         data = {
            "isRobot":false,
            "roomId":-1,
            "isVideo":true,
            "playerInfos":param1.report.sceneInfo.playerInfos,
            "frames":param1.report.frames,
            "dungeonInfo":{},
            "data":{
               "dungeonId":_loc2_,
               "battleType":param1.report.battleType
            },
            "dungeonId":_loc2_
         };
         QCOnServerFrame2.BU_Frame = false;
         if(data.frames && data.frames.length > 0)
         {
            _loc3_ = true;
            PlayPvpVideoCmd.lastFrame = data.frames[data.frames.length - 1].currFrame;
         }
         else
         {
            CreateComponent.createAutoWarnBar("没战斗内容");
         }
         var _loc6_:LevelConfigVO = BattleModelManager.getIns().getCurrLevelConfig();
         var _loc4_:LevelConfigVO = LevelModelManager.getIns().getLevelByID(_loc2_);
         PreloadMediator(ApplicationFacade.getInstance().retrieveMediator("PreloadMediator")).show();
         ApplicationFacade.getInstance().removeMediator("BattleMapMediator");
         BattleModelManager.getIns().screenTotal = _loc4_.sceneStart.length;
         BattleModelManager.getIns().levelInfo = _loc4_;
         _loc4_.fromLevelVo = _loc6_;
         BattleModelManager.getIns().init();
         var _loc5_:LevelParam;
         if((_loc5_ = BattleModelManager.getIns().levelParam) && _loc5_.config.getIsV2())
         {
            _loc5_.logic = new BattleLogic(_loc5_);
            _loc5_.logic.addMapLogic(_loc5_.getMapLogic());
            _loc5_.logic.buildReport(param1.report.sceneInfo,param1.report);
            _loc5_.isVideo = true;
         }
         ApplicationFacade.getInstance().sendNotification("CMD_GO_IN_BATTLE");
      }
      
      private function onDataLoadComplete(... rest) : void
      {
         var args:Array = rest;
         var res:Object = JSON.parse(args[0].data);
         ApplicationFacade.getInstance().removeMediator("BattleMapMediator");
         CGModelManager.isUse = res.report.cg != GlobalData.CurrCg;
         SimpleTextLog.getIns().log("onGetRepot cg=",res.report.cg,"GlobalData.CurrCg=" + GlobalData.CurrCg,"isUse=" + CGModelManager.isUse);
         if(CGModelManager.isUse)
         {
            CGModelManager.getIns().loadCg(res.report.cg,function():void
            {
               play(res);
            });
         }
         else
         {
            this.play(res);
         }
      }
   }
}
