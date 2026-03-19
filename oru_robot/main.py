
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oru_robot import (
    ObjectGraph,
    create_initial_state,
    ORUReplacementWorkflow,
    APIRAGService,
)
from utils.logger_handler import logger


def setup_object_graph():
    object_graph = ObjectGraph()
    
    config_file = "oru_robot/data/object_positions/example_setup.json"
    if os.path.exists(config_file):
        logger.info(f"加载物体配置: {config_file}")
        object_graph.load_from_file(config_file)
    else:
        logger.warning("未找到配置文件，使用空的ObjectGraph")
    
    return object_graph


def setup_rag():
    rag_service = APIRAGService()
    
    pdf_files = [
        "API_Reference_Control.pdf",
        "API_Reference_Receive.pdf"
    ]
    
    existing_pdfs = [f for f in pdf_files if os.path.exists(f)]
    if existing_pdfs:
        logger.info(f"加载API文档: {existing_pdfs}")
        rag_service.load_pdf_documents(existing_pdfs)
    else:
        logger.warning("未找到API文档PDF文件")
    
    return rag_service


def main():
    logger.info("=" * 60)
    logger.info("ORU更换机器人系统启动")
    logger.info("=" * 60)
    
    object_graph = setup_object_graph()
    logger.info("\n物体图状态:")
    print(object_graph.visualize())
    
    workflow = ORUReplacementWorkflow(object_graph)
    
    initial_state = create_initial_state(
        oru_old_id="oru_old_001",
        oru_new_id="oru_new_001",
        storage_rack_id="storage_rack_001",
        assembly_station_id="assembly_station_001",
        tool_rack_id="tool_rack_001",
        screwdriver_id="screwdriver_001",
        total_screws=4
    )
    
    logger.info("\n开始执行ORU更换流程...")
    final_state = workflow.run(initial_state)
    
    logger.info("\n" + "=" * 60)
    logger.info("执行结果:")
    logger.info("=" * 60)
    print(f"成功: {final_state['is_successful']}")
    print(f"完成步骤: {final_state['current_step_index']}/{final_state['total_steps']}")
    print(f"ORU已安装: {final_state['oru_installed']}")
    print(f"螺丝拧紧: {final_state['screws_tightened']}/{final_state['total_screws']}")
    
    if final_state['errors']:
        print("\n错误列表:")
        for i, error in enumerate(final_state['errors'], 1):
            print(f"  {i}. {error}")
    
    logger.info("\n系统关闭")


if __name__ == '__main__':
    main()

